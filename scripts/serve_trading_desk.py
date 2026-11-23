from __future__ import annotations

import argparse
import csv
import json
import os
import queue
import sys
import tempfile
import threading
import time
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.information.premarket_live import (  # noqa: E402
    PremarketLive,
    merge_live_market_pulse,
)
from fintech_quant.information.stock_intel import prune_daily_cache  # noqa: E402
from fintech_quant.reports.demo_fixtures import (  # noqa: E402
    DemoPaths,
    build_demo_workspace,
    demo_jev_payload,
    demo_premarket_context,
    demo_research_payload,
)
from fintech_quant.reports.desk import (  # noqa: E402
    build_desk_snapshot,
    cycle_fingerprint,
    load_quotes_csv,
    render_desk_html,
    watched_symbols,
)
from fintech_quant.reports.live_stock import LiveContext, intraday_payload  # noqa: E402
from fintech_quant.reports.picker import (  # noqa: E402
    PickerData,
    events_llm_payload,
    intraday_monitor_view,
    jev_payload,
    load_picker_data,
    picks_payload,
    research_payload,
    stock_payload,
    universe_payload,
)


PICKER_TEMPLATE = SRC / "fintech_quant" / "reports" / "picker_template.html"


HEARTBEAT_SECONDS = 15.0


class DeskState:
    """Holds the latest snapshot and fans it out to SSE subscribers. Read-only over cycle artifacts."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.demo = bool(getattr(args, "demo", False))
        self.demo_paths: DemoPaths | None = getattr(args, "_demo_paths", None)
        self._demo_premarket_cache: dict[str, object] | None = None
        self.premarket_live = PremarketLive(None if self.demo else args.premarket_root)
        self._turnover_cache: tuple[str, dict[str, float]] = ("", {})
        self.lock = threading.Lock()
        self.subscribers: list[queue.Queue[str]] = []
        self.quotes: list[dict[str, object]] = []
        self.quotes_status = "demo" if self.demo else "off"
        self.quotes_fetched_at = 0.0
        self.fingerprint: tuple[object, ...] | None = None
        self.snapshot: dict[str, object] = {}
        self.live = None if self.demo else LiveContext(cache_dir=args.intel_cache / "live")
        if not self.demo:
            threading.Thread(target=self._warm_universe, daemon=True).start()
        self.picker_lock = threading.Lock()
        self.picker_data: PickerData | None = None
        self.picker_mtime = 0
        self.pruned_on: date | None = None
        self.refresh(force=True)
        self.prune_cache()

    def refresh(self, *, force: bool = False) -> bool:
        extra = [self.args.quotes] if self.args.quotes else []
        fingerprint = cycle_fingerprint(self.args.cycle_root, extra)
        quotes_changed = self._refresh_quotes()
        if not force and not quotes_changed and fingerprint == self.fingerprint:
            return False
        snapshot = build_desk_snapshot(
            self.args.cycle_root,
            pnl_curve=self.args.pnl_curve,
            quotes=self.quotes,
            quotes_status=self.quotes_status,
        )
        with self.lock:
            self.fingerprint = fingerprint
            self.snapshot = snapshot
            message = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
            for subscriber in self.subscribers:
                subscriber.put(message)
        return True

    def _refresh_quotes(self) -> bool:
        if self.args.quotes:
            if not self.args.quotes.exists():
                self.quotes, self.quotes_status = [], "quotes file missing"
                return False
            self.quotes, self.quotes_status = load_quotes_csv(self.args.quotes), "file"
            return False  # file changes are covered by the fingerprint
        if not self.args.live_quotes:
            return False
        if time.monotonic() - self.quotes_fetched_at < self.args.quote_interval:
            return False
        self.quotes_fetched_at = time.monotonic()
        from fintech_quant.data import AkShareRealtimeQuoteProvider

        symbols = watched_symbols(self.snapshot) if self.snapshot else None
        try:
            self.quotes = AkShareRealtimeQuoteProvider().quotes(symbols)
            self.quotes_status = "live"
        except Exception as exc:  # provider outages must not kill the read-only view
            self.quotes_status = f"quote fetch failed: {exc}"
        return True

    def prune_cache(self) -> None:
        """Once per calendar day: drop intel/quote cache day folders older than 30 days."""
        today = date.today()
        if self.pruned_on == today:
            return
        self.pruned_on = today
        removed = prune_daily_cache(self.args.intel_cache, today=today)
        if removed:
            print(f"pruned {len(removed)} cache day folders older than 30 days", flush=True)

    def _warm_universe(self) -> None:
        try:
            self.live.all_shares()
        except Exception as exc:  # search falls back to CSI 300 members only
            print(f"all-A-share list unavailable: {exc}", file=sys.stderr, flush=True)

    def picker(self) -> PickerData:
        """Stock-picker data, reloaded whenever the pipeline state file changes."""
        mtime = self.args.state.stat().st_mtime_ns
        with self.picker_lock:
            if self.picker_data is None or mtime != self.picker_mtime:
                self.picker_data = load_picker_data(self.args.state)
                self.picker_mtime = mtime
            return self.picker_data

    def pool_state(self) -> dict[str, object] | None:
        path = self.args.pool_root / "state.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def pool_v2_state(self) -> dict[str, object] | None:
        path = self.args.pool_v2_root / "state.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def intraday_monitor(self) -> dict[str, object] | None:
        """The latest intraday plan, its triggers and the comparison summary, if any."""
        root = self.args.intraday_root
        plans = sorted(root.glob("*/plan.json"))
        if not plans:
            return None

        def read(path: Path) -> dict[str, object] | None:
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

        return intraday_monitor_view(
            self.picker(),
            read(plans[-1]),
            read(plans[-1].with_name("triggers.json")),
            read(root / "comparison.json"),
        )

    def scoring_v2_state(self) -> dict[str, object] | None:
        path = self.args.scoring_v2
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def premarket_context(
        self, *, refresh: bool = False, wait: bool = False, phase: str | None = None
    ) -> dict[str, object]:
        """Pre-market pulse, pitfall radar and 09:25 auction for `/picks`.

        The pulse and the calendar come from the brief the post-close job built for the latest
        cycle; an older brief is never shown as today's. Live A-share market temperature,
        overseas quotes, overnight notices and the auction are fetched on demand (see
        ``premarket_live``). ``phase="fast"`` skips the slow notice scan so cards paint
        immediately; ``phase="notices"`` runs the overnight notice scan; ``phase=None`` returns
        the backwards-compatible combined payload."""
        if self.demo and self.demo_paths is not None:
            if self._demo_premarket_cache is None:
                self._demo_premarket_cache = demo_premarket_context(self.demo_paths, self.picker())
            if phase == "notices":
                return {
                    "status": "ok",
                    "signal_date": self._demo_premarket_cache.get("signal_date"),
                    "pitfall_calendar": self._demo_premarket_cache.get("pitfall_calendar")
                    or {"status": "ok", "alerts": []},
                    "notices_updated_at": None,
                    "notices_pending": False,
                }
            return self._demo_premarket_cache

        with self.lock:
            signal_date = self.snapshot.get("as_of")
        brief = self._brief(str(signal_date)) if signal_date else None
        inputs = self._premarket_inputs(str(signal_date or ""), brief)
        if phase is None:
            live = self.premarket_live.snapshot(inputs, refresh=refresh, wait=wait)
        else:
            live = self.premarket_live.snapshot(inputs, refresh=refresh, wait=wait, phase=phase)
        watched = set(inputs["auction_symbols"])  # type: ignore[arg-type]

        calendar = dict((brief or {}).get("pitfall_calendar") or {"status": "not_checked", "alerts": []})
        alerts = [a for a in calendar.get("alerts", []) if a.get("symbol") in watched]
        notices = live.get("notices") or {}
        if notices.get("signal_date") in (None, signal_date):
            alerts += notices.get("alerts", [])
            if calendar.get("status") == "not_checked" and notices.get("status") not in (None, "not_checked"):
                calendar["status"] = "partial"
        calendar["alerts"] = alerts

        if phase == "notices":
            return {
                "status": "ok" if calendar.get("status") != "not_checked" else "unavailable",
                "signal_date": signal_date if brief else None,
                "pitfall_calendar": calendar,
                "notices_updated_at": notices.get("fetched_at"),
                "notices_pending": False,
                "live": {
                    "segment": live["segment"],
                    "refreshing": bool(live.get("refreshing", False)),
                    "brief": brief is not None,
                    "notices_fetched_at": notices.get("fetched_at"),
                    "notices_status": notices.get("status"),
                    "notices_checked": notices.get("checked"),
                },
            }

        market_pulse = merge_live_market_pulse(
            (brief or {}).get("market_pulse"),
            live.get("market_pulse"),
            signal_date=str(signal_date or "") or None,
        )
        overseas = live.get("overseas") or {}
        if overseas.get("items"):
            market_pulse["overseas"] = overseas["items"]
            if market_pulse.get("status") == "unavailable":
                market_pulse["status"] = "partial"

        auction = None
        raw = live.get("auction")
        if raw and raw.get("signal_date") == signal_date:
            auction = {
                key: raw.get(key)
                for key in ("signal_date", "benchmark_gap_pct", "near_limit_pct", "large_gap_pct", "mode", "captured_at")
            }
            auction["by_symbol"] = {str(c["symbol"]): c for c in raw.get("checks", [])}

        has_data = (
            market_pulse.get("status") != "unavailable"
            or calendar.get("status") != "not_checked"
            or auction is not None
        )
        notices_pending = bool(live.get("notices_pending", False))
        return {
            "status": "ok" if has_data else "unavailable",
            "signal_date": signal_date if brief else None,
            "market_pulse": market_pulse,
            "pitfall_calendar": calendar,
            "auction": auction,
            "notices_pending": notices_pending,
            "live": {
                "segment": live["segment"],
                "refreshing": bool(live.get("refreshing", False)),
                "brief": brief is not None,
                "overseas_fetched_at": overseas.get("fetched_at"),
                "notices_fetched_at": notices.get("fetched_at"),
                "notices_status": notices.get("status"),
                "notices_checked": notices.get("checked"),
                "notices_pending": notices_pending,
            },
        }

    def _brief(self, signal_date: str) -> dict[str, object] | None:
        path = self.args.premarket_root / signal_date / "brief.json"
        try:
            brief = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return brief if brief.get("signal_date") == signal_date else None

    def _premarket_inputs(self, signal_date: str, brief: dict[str, object] | None) -> dict[str, object]:
        """Symbols shown on `/picks` (brief rows, both pools, candidates) and what the auction
        check needs for them. Picker data is optional: without it only the brief rows count."""
        groups = {g: [str(i["symbol"]) for i in (brief or {}).get(g, [])] for g in ("targets", "near_miss", "paper_exits")}
        names = {str(i["symbol"]): str(i.get("name", "")) for g in groups for i in (brief or {}).get(g, [])}
        pool_symbols: list[str] = []
        candidates: list[str] = []
        luk: dict[str, dict[str, object]] = {}
        try:
            data = self.picker()
            picks = picks_payload(data, self.pool_state(), self.pool_v2_state())
            pool_symbols = _symbols([picks.get("pool"), picks.get("pool_v2")])
            candidates = _symbols(picks.get("candidates"))
            names = {**data.names, **names}
            for row in data.screen_results:
                ratio = data.price_ratio.get(str(row["symbol"]), 1.0)
                luk[str(row["symbol"])] = {
                    "state": row["state"],
                    "stop_price": round(float(row["stop"]) * ratio, 3),
                    "stop_pct": row["stop_pct"],
                }
        except Exception as exc:  # the panel still works from the brief alone
            print(f"premarket inputs without picker data: {exc}", file=sys.stderr, flush=True)
        notice = _dedupe(groups["targets"] + groups["paper_exits"] + pool_symbols + groups["near_miss"])
        watch = _dedupe(notice + candidates)
        return {
            "signal_date": signal_date,
            "brief": brief,
            "names": names,
            "notice_symbols": notice,
            "auction_symbols": watch,
            "luk_setup": luk,
            "avg_turnover_20d": self._avg_turnover(signal_date),
        }

    def _avg_turnover(self, signal_date: str) -> dict[str, float]:
        """20-session average turnover per member from the cycle's execution prices (cached per date)."""
        if self._turnover_cache[0] == signal_date:
            return self._turnover_cache[1]
        averages: dict[str, float] = {}
        try:
            state = json.loads(self.args.state.read_text(encoding="utf-8"))
            manifest = Path(state["manifests"]["execution_price"]["processed_manifest"])
            history: dict[str, list[float]] = {}
            with (manifest.parent / "daily.csv").open(encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    if row["trade_date"] <= signal_date and row["amount"]:
                        history.setdefault(row["symbol"], []).append(float(row["amount"]))
            averages = {s: sum(v[-20:]) / len(v[-20:]) for s, v in history.items() if len(v) >= 20}
        except (OSError, KeyError, ValueError) as exc:
            print(f"20-day turnover unavailable: {exc}", file=sys.stderr, flush=True)
        self._turnover_cache = (signal_date, averages)
        return averages

    def subscribe(self) -> queue.Queue[str]:
        subscriber: queue.Queue[str] = queue.Queue()
        with self.lock:
            self.subscribers.append(subscriber)
            subscriber.put(json.dumps(self.snapshot, ensure_ascii=False, separators=(",", ":")))
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue[str]) -> None:
        with self.lock:
            if subscriber in self.subscribers:
                self.subscribers.remove(subscriber)


def _symbols(value: object) -> list[str]:
    """Every A-share symbol under a ``"symbol"`` key, in order of appearance."""
    found: list[str] = []
    if isinstance(value, dict):
        symbol = value.get("symbol")
        if isinstance(symbol, str) and symbol[-3:] in (".SH", ".SZ", ".BJ"):
            found.append(symbol)
        for child in value.values():
            found += _symbols(child)
    elif isinstance(value, list):
        for child in value:
            found += _symbols(child)
    return _dedupe(found)


def _dedupe(symbols: list[str]) -> list[str]:
    return list(dict.fromkeys(symbols))


def make_handler(state: DeskState) -> type[BaseHTTPRequestHandler]:
    class DeskHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path == "/":
                with state.lock:
                    body = render_desk_html(state.snapshot, live=True).encode("utf-8")
                self._send(body, "text/html; charset=utf-8")
            elif path == "/api/snapshot":
                with state.lock:
                    body = json.dumps(state.snapshot, ensure_ascii=False).encode("utf-8")
                self._send(body, "application/json; charset=utf-8")
            elif path == "/api/stream":
                self._stream()
            elif path == "/picks":
                as_of = state.picker().as_of
                body = PICKER_TEMPLATE.read_text(encoding="utf-8").replace(
                    "__PICKER_TITLE__", f"选股 · CSI 300 · {as_of}"
                )
                self._send(body.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/api/premarket-context":
                qs = parse_qs(urlsplit(self.path).query)
                refresh = qs.get("refresh") == ["1"]
                raw_phase = (qs.get("phase") or [""])[0].strip().lower()
                phase = raw_phase if raw_phase in ("fast", "notices") else None
                self._json(state.premarket_context(refresh=refresh, phase=phase))
            elif path == "/api/universe":
                self._json(universe_payload(state.picker(), state.live))
            elif path == "/api/picks":
                self._json(picks_payload(state.picker(), state.pool_state(), state.pool_v2_state()))
            elif path == "/api/stock":
                self._json(
                    stock_payload(  # each 分析 press refetches the stock's data
                        state.picker(),
                        self._query(),
                        state.live,
                        state.scoring_v2_state(),
                        fresh=not state.demo,
                    )
                )
            elif path == "/api/intraday-monitor":
                self._json(state.intraday_monitor())
            elif path == "/api/intraday":
                if state.demo or state.live is None:
                    self._json({"error": "Demo 模式为离线静态行情，不含盘中分时数据"})
                else:
                    self._json(intraday_payload(state.live, self._query()))
            elif path == "/api/research":
                if state.demo:
                    self._json(demo_research_payload(state.picker(), self._query()))
                else:
                    self._json(
                        research_payload(
                            state.picker(),
                            self._query(),
                            cache_dir=state.args.intel_cache,
                            jev_record_dir=state.args.jev_records,
                            live=state.live,
                        )
                    )
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path == "/api/events_llm":
                if state.demo:
                    self._json({"error": "Demo 模式不调用外部 LLM API"})
                    return
                try:
                    result = events_llm_payload(
                        state.picker(),
                        self._query(),
                        cache_dir=state.args.intel_cache,
                        live=state.live,
                    )
                except Exception as exc:  # LLM/network failures are reported, not fatal
                    result = {"error": f"LLM 辅助判定失败：{type(exc).__name__}: {str(exc)[:200]}"}
                self._json(result)
                return
            if path != "/api/jev":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if state.demo:
                self._json(demo_jev_payload(state.picker(), self._query()))
                return
            try:
                payload = jev_payload(
                    state.picker(),
                    self._query(),
                    cache_dir=state.args.intel_cache,
                    jev_record_dir=state.args.jev_records,
                    live=state.live,
                )
            except Exception as exc:  # LLM/network failures are reported, not fatal
                payload = {"error": f"Jev 调用失败：{type(exc).__name__}: {str(exc)[:200]}"}
            self._json(payload)

        def _query(self) -> str:
            return parse_qs(urlsplit(self.path).query).get("q", [""])[0]

        def _json(self, payload: object) -> None:
            self._send(
                json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                "application/json; charset=utf-8",
            )

        def _send(self, body: bytes, content_type: str) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _stream(self) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            subscriber = state.subscribe()
            try:
                while True:
                    try:
                        message = subscriber.get(timeout=HEARTBEAT_SECONDS)
                        self.wfile.write(f"event: snapshot\ndata: {message}\n\n".encode("utf-8"))
                    except queue.Empty:
                        self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                state.unsubscribe(subscriber)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            if self.path.startswith("/api/stream"):
                return
            super().log_message(format, *args)

    return DeskHandler


def watch(state: DeskState, interval: float, stop: threading.Event) -> None:
    while not stop.wait(interval):
        try:
            state.prune_cache()
            if state.refresh():
                print(f"desk snapshot updated as_of={state.snapshot.get('as_of')}", flush=True)
        except Exception as exc:  # a half-written cycle directory is retried on the next poll
            print(f"desk refresh skipped: {exc}", file=sys.stderr, flush=True)


def load_env_file(path: Path) -> list[str]:
    """Load KEY=VALUE lines from a local .env without overriding the real environment."""
    if not path.is_file():
        return []
    loaded = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        value = value.strip("'\"")
        if key and value and key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded


def build_parser() -> argparse.ArgumentParser:
    """Defaults are anchored at the project root, so the desk finds the canonical artifacts
    whatever directory it is started from."""
    parser = argparse.ArgumentParser(
        description="Serve the read-only CSI 300 trading-desk dashboard."
    )
    parser.add_argument(
        "--cycle-root", type=Path, default=ROOT / "outputs/paper_trading/csi300_baseline/cycles"
    )
    parser.add_argument(
        "--pnl-curve",
        type=Path,
        default=ROOT / "outputs/csi300_research/hfq-formal-20260713/pnl_curve.json",
    )
    parser.add_argument(
        "--state", type=Path, default=ROOT / "data/paper/csi300_baseline/pipeline_state.json"
    )
    parser.add_argument("--pool-root", type=Path, default=ROOT / "outputs/momentum_pool")
    parser.add_argument("--pool-v2-root", type=Path, default=ROOT / "outputs/momentum_pool_v2")
    parser.add_argument(
        "--intraday-root", type=Path, default=ROOT / "outputs/momentum_pool_intraday"
    )
    parser.add_argument(
        "--scoring-v2",
        type=Path,
        default=ROOT / "outputs/research/scoring_v2/latest_scores.json",
        help="Research v2 score snapshot shown in the picker (not used by the counted strategy).",
    )
    parser.add_argument("--intel-cache", type=Path, default=ROOT / "outputs/research_cache")
    parser.add_argument("--jev-records", type=Path, default=ROOT / "outputs/jev")
    parser.add_argument(
        "--premarket-root",
        type=Path,
        default=ROOT / "outputs/premarket",
        help="Directory holding pre-market briefs (<date>/brief.json and optional auction.json).",
    )
    parser.add_argument("--quotes", type=Path, default=None, help="Realtime quote CSV to watch.")
    parser.add_argument("--live-quotes", action="store_true", help="Poll AkShare spot quotes.")
    parser.add_argument("--quote-interval", type=float, default=30.0)
    parser.add_argument("--poll", type=float, default=5.0, help="Seconds between artifact checks.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--export", type=Path, default=None, help="Write a static HTML snapshot and exit."
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Launch with built-in fictional A-share sample data (offline; needs only numpy and pandas).",
    )
    return parser


def _apply_demo_paths(args: argparse.Namespace, demo_root: Path) -> None:
    demo = build_demo_workspace(demo_root)
    args._demo_paths = demo
    args.cycle_root = demo.cycle_root
    args.pnl_curve = demo.pnl_curve
    args.state = demo.state
    args.pool_root = demo.pool_root
    args.pool_v2_root = demo.pool_v2_root
    args.intraday_root = demo.intraday_root
    args.scoring_v2 = demo.scoring_v2
    args.intel_cache = demo.intel_cache
    args.jev_records = demo.jev_records
    args.premarket_root = demo.root / "premarket"
    args.quotes = None
    args.live_quotes = False


def main() -> int:
    loaded = load_env_file(ROOT / ".env")
    if loaded:
        print(f"loaded .env keys: {', '.join(sorted(loaded))}", flush=True)
    args = build_parser().parse_args()

    demo_dir: tempfile.TemporaryDirectory[str] | None = None
    if args.demo:
        demo_dir = tempfile.TemporaryDirectory(prefix="vibe-trading-demo-")
        _apply_demo_paths(args, Path(demo_dir.name))

    try:
        if args.export:
            snapshot = build_desk_snapshot(
                args.cycle_root,
                pnl_curve=args.pnl_curve,
                quotes=(
                    load_quotes_csv(args.quotes)
                    if args.quotes and args.quotes.exists()
                    else None
                ),
                quotes_status="demo" if args.demo else None,
            )
            args.export.parent.mkdir(parents=True, exist_ok=True)
            args.export.write_text(render_desk_html(snapshot, live=False), encoding="utf-8")
            print(f"output={args.export}")
            return 0

        state = DeskState(args)
        stop = threading.Event()
        threading.Thread(target=watch, args=(state, args.poll, stop), daemon=True).start()
        server = ThreadingHTTPServer((args.host, args.port), make_handler(state))
        server.daemon_threads = True
        mode_tag = " [DEMO]" if args.demo else ""
        print(
            f"trading desk on http://{args.host}:{args.port} "
            f"(picker at /picks) as_of={state.snapshot.get('as_of')}{mode_tag}",
            flush=True,
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            stop.set()
            server.server_close()
        return 0
    finally:
        if demo_dir is not None:
            demo_dir.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
