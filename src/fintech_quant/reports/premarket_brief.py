"""Pre-market stock-selection brief for a human trader.

The brief only reads a completed V2 post-close cycle. It never writes into the
cycle directory, the paper account, or the pipeline state, and it introduces no
strategy logic of its own: targets, scores, risk warnings and thresholds all come
from the cycle's recorded artifacts and policy. An optional scoring-v2 research
snapshot is shown next to the counted score for comparison; it never selects or
sizes a target.
"""

from __future__ import annotations

import csv
import hashlib
import html
import json
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from fintech_quant.backtesting.constraints import AShareTradingConstraints
from fintech_quant.backtesting.costs import AShareCostModel
from fintech_quant.research.scoring_v2 import snapshot_view

BRIEF_SCHEMA_VERSION = 1
CYCLE_FILES = ("cycle_manifest.json", "targets.csv", "paper_report.json", "decision_report.json")
# Exchange rule change: SSE/SZSE main-board risk-warning (ST) stocks moved from a
# 5% to a 10% daily price limit on 2025-07-07.
MAIN_BOARD_ST_10PCT_FROM = date(2025, 7, 7)
STAR_MINIMUM_BUY_SHARES = 200


def price_limit_rate(symbol: str, name: str, trade_date: date) -> float:
    """Daily price-limit rate for an A-share on ``trade_date``."""
    code, _, exchange = symbol.partition(".")
    if exchange == "BJ":
        return 0.30
    if code.startswith(("688", "689", "300", "301")):
        return 0.20
    if "ST" in name.upper() and trade_date < MAIN_BOARD_ST_10PCT_FROM:
        return 0.05
    return 0.10


def limit_prices(previous_close: float, rate: float) -> tuple[float, float]:
    """Limit-up and limit-down prices, rounded half-up to the 0.01 tick."""
    if previous_close <= 0:
        raise ValueError("previous_close must be positive")
    base = Decimal(str(previous_close))
    step = Decimal(str(rate))
    tick = Decimal("0.01")
    up = (base * (1 + step)).quantize(tick, rounding=ROUND_HALF_UP)
    down = (base * (1 - step)).quantize(tick, rounding=ROUND_HALF_UP)
    return float(up), float(down)


def suggested_lot_quantity(
    capital: float,
    weight: float,
    price: float,
    symbol: str,
    cost_model: AShareCostModel | None = None,
    lot_size: int = AShareTradingConstraints().lot_size,
) -> dict[str, object]:
    """Whole board lots whose cost plus buy commission fits ``capital * weight``."""
    if capital <= 0 or price <= 0:
        raise ValueError("capital and price must be positive")
    if not 0 <= weight <= 1:
        raise ValueError("weight must be within [0, 1]")
    model = cost_model or AShareCostModel()
    allocation = capital * weight
    shares = int(allocation // (price * lot_size)) * lot_size
    while shares > 0:
        notional = shares * price
        if notional + model.buy_cost(notional, date.min).total <= allocation:
            break
        shares -= lot_size
    reason = None
    if shares == 0:
        reason = "allocation_below_one_lot"
    elif symbol.startswith(("688", "689")) and shares < STAR_MINIMUM_BUY_SHARES:
        shares, reason = 0, "star_minimum_200_shares"
    notional = round(shares * price, 2)
    return {
        "allocation": round(allocation, 2),
        "shares": shares,
        "notional": notional,
        "estimated_commission": model.buy_cost(notional, date.min).total if shares else 0.0,
        "reason": reason,
    }


def latest_complete_cycle(cycle_root: Path) -> Path:
    complete = sorted(
        path
        for path in cycle_root.iterdir()
        if path.is_dir() and all((path / name).is_file() for name in CYCLE_FILES)
    )
    if not complete:
        raise FileNotFoundError(f"no complete cycle under {cycle_root}")
    return complete[-1]


def build_brief(
    cycle_dir: Path,
    capital: float,
    near_miss_floor: float = 65.0,
    scoring_v2_path: Path | None = None,
) -> dict[str, object]:
    manifest = _load_json(cycle_dir / "cycle_manifest.json")
    if manifest.get("schema_version") != 2 or manifest.get("kind") != "paper_trading_cycle":
        raise ValueError("cycle manifest is not a V2 paper_trading_cycle")
    as_of = date.fromisoformat(str(manifest["as_of"]))
    policy = manifest["policy"]
    buy_threshold = float(policy["buy_threshold"])
    if not near_miss_floor < buy_threshold:
        raise ValueError("near_miss_floor must be below the recorded buy threshold")

    targets_path = cycle_dir / "targets.csv"
    paper_path = cycle_dir / "paper_report.json"
    decision_path = cycle_dir / "decision_report.json"
    _verify(targets_path, manifest["artifacts"]["targets"])
    _verify(paper_path, manifest["artifacts"]["paper_report"])
    execution_prices = Path(manifest["inputs"]["execution_prices"]["path"])
    _verify(execution_prices, manifest["inputs"]["execution_prices"])
    universe_ref = manifest["inputs"]["current_universe"]
    universe_path = cycle_dir / Path(universe_ref["path"]).name
    _verify(universe_path, universe_ref)

    targets = {row["symbol"]: row for row in _read_csv(targets_path)}
    account = _load_json(paper_path)["account"]
    if account.get("pending_signal_date") != as_of.isoformat():
        raise ValueError("paper account pending signal date does not match the cycle")
    if set(account.get("pending_targets", {})) != set(targets):
        raise ValueError("targets.csv does not match the paper account pending targets")
    decision = _load_json(decision_path)
    if decision.get("as_of") != as_of.isoformat():
        raise ValueError("decision report as_of does not match the cycle")
    names = {row["symbol"]: row.get("name", "") for row in _read_csv(universe_path)}

    scores = {row["symbol"]: row for row in decision["scores"]}
    near_miss = sorted(
        (
            symbol
            for symbol, row in scores.items()
            if symbol not in targets and near_miss_floor <= float(row["total"]) < buy_threshold
        ),
        key=lambda symbol: (-float(scores[symbol]["total"]), symbol),
    )
    positions = account.get("positions", {})
    exits = sorted(symbol for symbol in positions if symbol not in targets)
    symbols = sorted(targets) + near_miss + exits
    closes = _previous_closes(execution_prices, set(symbols), as_of)
    warnings_by_symbol: dict[str, list[dict[str, object]]] = {}
    for warning in decision.get("risk_warnings", []):
        warnings_by_symbol.setdefault(str(warning["symbol"]), []).append(warning)

    v2_snapshot, v2_status = _scoring_v2_snapshot(scoring_v2_path, as_of)

    cost_model = AShareCostModel(
        commission_rate=float(policy["commission_rate"]),
        minimum_commission=float(policy["minimum_commission"]),
    )
    max_weight = float(policy["maximum_position_weight"])

    def entry(symbol: str, category: str) -> dict[str, object]:
        name = names.get(symbol, "")
        close_date, close = closes.get(symbol, (None, None))
        flags = [
            {"rule": w["rule"], "action": w["action"], "message": w["message"]}
            for w in warnings_by_symbol.get(symbol, [])
        ]
        score = scores.get(symbol)
        if score and score.get("missing_fields"):
            flags.append({"rule": "missing_score_fields", "fields": score["missing_fields"]})
        if "ST" in name.upper():
            flags.append({"rule": "risk_warning_st_name"})
        item: dict[str, object] = {
            "symbol": symbol,
            "name": name,
            "category": category,
            "score": _score_breakdown(score),
            "scoring_v2": (
                snapshot_view(v2_snapshot, symbol, as_of.isoformat())
                if v2_snapshot is not None and category in {"target", "near_miss"}
                else None
            ),
            "risk_flags": flags,
            "paper_position_shares": int(positions.get(symbol, {}).get("shares", 0)),
            "previous_close": close,
            "previous_close_date": close_date,
            "overnight_announcements": {"status": "not_checked", "items": []},
        }
        if close is None:
            flags.append({"rule": "no_previous_close"})
            item.update(limit_rate=None, limit_up=None, limit_down=None, suggested=None)
            return item
        if close_date != as_of.isoformat():
            flags.append({"rule": "stale_previous_close", "close_date": close_date})
        rate = price_limit_rate(symbol, name, as_of)
        up, down = limit_prices(close, rate)
        item.update(limit_rate=rate, limit_up=up, limit_down=down)
        if category == "target":
            row = targets[symbol]
            item["raw_target_weight"] = float(row["raw_target_weight"])
            item["target_weight"] = float(row["target_weight"])
            item["suggested"] = suggested_lot_quantity(
                capital, float(row["target_weight"]), close, symbol, cost_model
            )
        elif category == "near_miss":
            item["suggested"] = None
            item["hypothetical_at_max_weight"] = suggested_lot_quantity(
                capital, max_weight, close, symbol, cost_model
            )
        else:
            item["suggested"] = {"shares": 0, "reason": "paper_exit_target_weight_zero"}
        return item

    return {
        "schema_version": BRIEF_SCHEMA_VERSION,
        "kind": "premarket_brief",
        "signal_date": as_of.isoformat(),
        "execution": "next A-share session open after signal_date; a human places every order",
        "capital": capital,
        "near_miss_floor": near_miss_floor,
        "policy": dict(policy),
        "counts_toward_paper_evidence": False,
        "live_trading_enabled": False,
        "sources": {
            "cycle_manifest": _reference(cycle_dir / "cycle_manifest.json"),
            "targets": _reference(targets_path),
            "paper_report": _reference(paper_path),
            "decision_report": _reference(decision_path),
            "current_universe": _reference(universe_path),
            "execution_prices": manifest["inputs"]["execution_prices"],
        },
        "scoring_v2": v2_status,
        "systemic_risk": decision.get("risk_summary", {}),
        "targets": [entry(symbol, "target") for symbol in sorted(targets)],
        "near_miss": [entry(symbol, "near_miss") for symbol in near_miss],
        "paper_exits": [entry(symbol, "paper_exit") for symbol in exits],
    }


def _scoring_v2_snapshot(
    path: Path | None, as_of: date
) -> tuple[Mapping[str, object] | None, dict[str, object]]:
    """The research snapshot when it is for the signal date; otherwise only its status."""
    if path is None or not path.is_file():
        return None, {"status": "missing", "counted": False}
    snapshot = _load_json(path)
    status: dict[str, object] = {
        "status": "ok" if snapshot.get("as_of") == as_of.isoformat() else "stale_snapshot",
        "as_of": snapshot.get("as_of"),
        "label": snapshot.get("label"),
        "weights": snapshot.get("weights"),
        "signs": snapshot.get("signs"),
        "counted": False,
        "source": _reference(path),
    }
    return (snapshot if status["status"] == "ok" else None), status


def evaluate_auction(
    brief: Mapping[str, object],
    quotes: Sequence[Mapping[str, str]],
    near_limit_pct: float = 0.01,
    large_gap_pct: float = 0.05,
) -> dict[str, object]:
    """Flag 09:25 auction prices against the brief's limit levels."""
    by_symbol = {str(row["symbol"]): row for row in quotes}
    capital = float(brief["capital"])
    cost_model = AShareCostModel(
        commission_rate=float(brief["policy"]["commission_rate"]),
        minimum_commission=float(brief["policy"]["minimum_commission"]),
    )
    checks = []
    for item in [*brief["targets"], *brief["near_miss"]]:
        symbol = str(item["symbol"])
        quote = by_symbol.get(symbol)
        check: dict[str, object] = {"symbol": symbol, "category": item["category"], "flags": []}
        price = float(quote["price"]) if quote and str(quote.get("price", "")).strip() else 0.0
        previous_close = item.get("previous_close")
        if price <= 0 or previous_close is None:
            check["flags"].append("no_auction_quote")
            checks.append(check)
            continue
        gap = price / float(previous_close) - 1.0
        check.update(auction_price=price, gap_pct=round(gap, 6))
        limit_up, limit_down = float(item["limit_up"]), float(item["limit_down"])
        if price >= limit_up:
            check["flags"].append("at_limit_up_cannot_buy")
        elif price >= limit_up * (1.0 - near_limit_pct):
            check["flags"].append("near_limit_up")
        elif gap >= large_gap_pct:
            check["flags"].append("large_gap_up")
        if price <= limit_down:
            check["flags"].append("at_limit_down")
        elif gap <= -large_gap_pct:
            check["flags"].append("large_gap_down")
        if item["category"] == "target":
            check["suggested_at_auction"] = suggested_lot_quantity(
                capital, float(item["target_weight"]), price, symbol, cost_model
            )
        checks.append(check)
    return {
        "schema_version": BRIEF_SCHEMA_VERSION,
        "kind": "premarket_auction_check",
        "signal_date": brief["signal_date"],
        "near_limit_pct": near_limit_pct,
        "large_gap_pct": large_gap_pct,
        "counts_toward_paper_evidence": False,
        "checks": checks,
    }


def write_once(path: Path, text: str) -> None:
    """Create ``path``; an existing file must already hold identical content."""
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise FileExistsError(f"{path} already exists with different content")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(text)


def ensure_outside(path: Path, protected: Sequence[Path]) -> None:
    resolved = path.resolve()
    for root in protected:
        root = root.resolve()
        if resolved == root or root in resolved.parents:
            raise ValueError(f"refusing to write {path} inside protected evidence path {root}")


def dumps(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_brief_html(
    brief: Mapping[str, object], auction: Mapping[str, object] | None = None
) -> str:
    checks = {c["symbol"]: c for c in auction["checks"]} if auction else {}
    sections = []
    for title, items in (
        ("Paper targets", brief["targets"]),
        ("Near misses (watch only, not targets)", brief["near_miss"]),
        ("Paper exits", brief["paper_exits"]),
    ):
        rows = "".join(_html_row(item, checks.get(item["symbol"])) for item in items)
        sections.append(
            f"<h2>{_e(title)} ({len(items)})</h2>"
            + (
                "<div class='scroll'><table><tr><th>Symbol</th><th>Score</th>"
                "<th>v2 research</th><th>Prev close</th>"
                "<th>Limit down / up</th><th>Suggested shares</th><th>Auction</th>"
                "<th>Risk flags</th><th>Overnight announcements</th></tr>"
                f"{rows}</table></div>"
                if items
                else "<p>None.</p>"
            )
        )
    systemic = brief.get("systemic_risk") or {}
    title = f"Pre-market brief — signal {brief['signal_date']}"
    return (
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{_e(title)}</title><style>{_CSS}</style></head><body>"
        f"<h1>{_e(title)}</h1>"
        f"<p class='note'>Research only. Orders are placed by a human at the next session open. "
        f"Capital {brief['capital']:,.0f}; buy threshold {brief['policy']['buy_threshold']}; "
        f"min confidence {brief['policy']['minimum_score_confidence']}. "
        f"Systemic warnings: {_e(json.dumps(systemic.get('by_rule', {}), ensure_ascii=False))}. "
        "This brief and the human ledger never count toward V2 paper evidence.</p>"
        + f"<p class='note'>{_e(_v2_note(brief.get('scoring_v2') or {}))}</p>"
        + (
            f"<p class='note'>Auction check applied (near limit {auction['near_limit_pct']:.0%}, "
            f"large gap {auction['large_gap_pct']:.0%}).</p>"
            if auction
            else ""
        )
        + "".join(sections)
        + "</body></html>\n"
    )


def _html_row(item: Mapping[str, object], check: Mapping[str, object] | None) -> str:
    score = item.get("score") or {}
    parts = "<br>".join(
        f"{_e(k)} {v['score']}/{v['max_score']}: {_e('; '.join(v['reasons']))}"
        for k, v in sorted((score.get("components") or {}).items())
    )
    suggested = item.get("suggested") or item.get("hypothetical_at_max_weight") or {}
    shares = suggested.get("shares", "")
    if item.get("hypothetical_at_max_weight"):
        shares = f"({shares} hypothetical)"
    if suggested.get("reason"):
        shares = f"{shares} [{suggested['reason']}]"
    auction_cell = ""
    if check:
        price = check.get("auction_price")
        auction_cell = (f"{price} ({check['gap_pct']:+.2%}) " if price else "") + " ".join(
            check["flags"]
        )
    flags = "<br>".join(_e(_flag_text(flag)) for flag in item["risk_flags"])
    return (
        f"<tr><td><b>{_e(item['symbol'])}</b><br>{_e(item['name'])}</td>"
        f"<td><b>{score.get('total', '')}</b> conf {score.get('confidence', '')}<br>"
        f"<small>{parts}</small></td>"
        f"<td>{_v2_cell(item.get('scoring_v2'), item['category'])}</td>"
        f"<td>{item.get('previous_close')}</td>"
        f"<td>{item.get('limit_down')} / {item.get('limit_up')}</td>"
        f"<td>{_e(str(shares))}</td><td class='flag'>{_e(auction_cell)}</td>"
        f"<td><small>{flags}</small></td><td>☐ not checked</td></tr>"
    )


V2_CATEGORY_LABELS = {
    "value": "value",
    "quality_growth": "quality/growth",
    "low_risk": "low risk",
    "liquidity": "low turnover",
    "reversal": "reversal",
    "momentum": "momentum 12-1",
}


def _v2_note(status: Mapping[str, object]) -> str:
    state = status.get("status")
    if state == "ok":
        return (
            "v2 research = cross-sectional percentile (0-100) of the scoring-v2 rank composite "
            f"for {status['as_of']}, with category percentiles and training ICIR weights. "
            "Factor signs follow the training ICIR; inverted (lower ranks higher): "
            + (", ".join(sorted(n for n, v in dict(status.get("signs") or {}).items() if v < 0))
               or "none")
            + ". Display only: it does not select or size any target and does not count toward "
            "paper evidence."
        )
    if state == "stale_snapshot":
        return (
            f"v2 research score not shown: its snapshot is for {status.get('as_of')}, not the "
            "signal date. Rerun scripts/run_scoring_v2.py after the post-close cycle."
        )
    return "v2 research score not shown: no snapshot (scripts/run_scoring_v2.py)."


def _v2_cell(view: Mapping[str, object] | None, category: str) -> str:
    if category == "paper_exit":
        return ""
    if not view:
        return "—"
    if view.get("score") is None:
        return "not scored"
    categories = view.get("categories") or {}
    parts = "<br>".join(
        f"{_e(label)} {categories[key]['percentile']:.0f} "
        f"(w {categories[key]['weight'] * 100:.0f}%)"
        for key, label in V2_CATEGORY_LABELS.items()
        if key in categories
    )
    return (
        f"<b>{view['score']:.1f}</b> pct · cov {view['coverage']:.0%}<br><small>{parts}</small>"
    )


def _flag_text(flag: Mapping[str, object]) -> str:
    detail = flag.get("message") or ", ".join(
        ", ".join(map(str, value)) if isinstance(value, list) else str(value)
        for key, value in flag.items()
        if key not in {"rule", "action"}
    )
    return f"{flag['rule']}: {detail}" if detail else str(flag["rule"])


def _score_breakdown(score: Mapping[str, object] | None) -> dict[str, object] | None:
    if score is None:
        return None
    return {
        "total": score["total"],
        "confidence": score["confidence"],
        "components": score["components"],
        "missing_fields": score.get("missing_fields", []),
    }


def _previous_closes(
    path: Path, symbols: set[str], as_of: date
) -> dict[str, tuple[str, float]]:
    latest: dict[str, tuple[str, float]] = {}
    cutoff = as_of.isoformat()
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            symbol = row["symbol"]
            if symbol not in symbols or row["trade_date"] > cutoff or not row["close"]:
                continue
            if symbol not in latest or row["trade_date"] > latest[symbol][0]:
                latest[symbol] = (row["trade_date"], float(row["close"]))
    return latest


def _verify(path: Path, reference: Mapping[str, object]) -> None:
    actual = _sha256(path)
    if actual != reference["sha256"]:
        raise ValueError(f"{path} hash {actual} does not match manifest {reference['sha256']}")


def _reference(path: Path) -> dict[str, object]:
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": _sha256(path)}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _e(value: object) -> str:
    return html.escape(str(value))


_CSS = """
body{font:14px/1.5 -apple-system,system-ui,sans-serif;margin:16px;color:#1d1d1f;background:#fff}
table{border-collapse:collapse;width:100%;margin-bottom:24px}.scroll{overflow-x:auto}
th,td{border:1px solid #d2d2d7;padding:6px 8px;vertical-align:top;text-align:left}
td:nth-child(2){min-width:280px}th{background:#f5f5f7}.note{color:#555}.flag{color:#b3261e;font-weight:600}
@media (prefers-color-scheme:dark){body{background:#111;color:#eee}th{background:#222}
th,td{border-color:#444}.note{color:#aaa}.flag{color:#ff8a80}}
"""
