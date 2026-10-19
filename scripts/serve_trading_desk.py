from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.reports.desk import (  # noqa: E402
    build_desk_snapshot,
    cycle_fingerprint,
    load_quotes_csv,
    render_desk_html,
    watched_symbols,
)
from fintech_quant.reports.live_stock import LiveContext  # noqa: E402
from fintech_quant.reports.picker import (  # noqa: E402
    PickerData,
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
        self.lock = threading.Lock()
        self.subscribers: list[queue.Queue[str]] = []
        self.quotes: list[dict[str, object]] = []
        self.quotes_status = "off"
        self.quotes_fetched_at = 0.0
        self.fingerprint: tuple[object, ...] | None = None
        self.snapshot: dict[str, object] = {}
        self.live = LiveContext(cache_dir=args.intel_cache / "live")
        threading.Thread(target=self._warm_universe, daemon=True).start()
        self.picker_lock = threading.Lock()
        self.picker_data: PickerData | None = None
        self.picker_mtime = 0
        self.refresh(force=True)

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

    def scoring_v2_state(self) -> dict[str, object] | None:
        path = self.args.scoring_v2
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

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
            elif path == "/api/universe":
                self._json(universe_payload(state.picker(), state.live))
            elif path == "/api/picks":
                self._json(picks_payload(state.picker(), state.pool_state(), state.pool_v2_state()))
            elif path == "/api/stock":
                self._json(
                    stock_payload(
                        state.picker(), self._query(), state.live, state.scoring_v2_state()
                    )
                )
            elif path == "/api/research":
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
            if self.path.split("?", 1)[0] != "/api/jev":
                self.send_error(HTTPStatus.NOT_FOUND)
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


def main() -> int:
    loaded = load_env_file(ROOT / ".env")
    if loaded:
        print(f"loaded .env keys: {', '.join(sorted(loaded))}", flush=True)
    parser = argparse.ArgumentParser(
        description="Serve the read-only CSI 300 trading-desk dashboard."
    )
    parser.add_argument(
        "--cycle-root", type=Path, default=Path("outputs/paper_trading/csi300_baseline/cycles")
    )
    parser.add_argument(
        "--pnl-curve",
        type=Path,
        default=Path("outputs/csi300_research/hfq-formal-20260713/pnl_curve.json"),
    )
    parser.add_argument(
        "--state", type=Path, default=Path("data/paper/csi300_baseline/pipeline_state.json")
    )
    parser.add_argument("--pool-root", type=Path, default=Path("outputs/momentum_pool"))
    parser.add_argument("--pool-v2-root", type=Path, default=Path("outputs/momentum_pool_v2"))
    parser.add_argument(
        "--scoring-v2",
        type=Path,
        default=Path("outputs/research/scoring_v2/latest_scores.json"),
        help="Research v2 score snapshot shown in the picker (not used by the counted strategy).",
    )
    parser.add_argument("--intel-cache", type=Path, default=Path("outputs/research_cache"))
    parser.add_argument("--jev-records", type=Path, default=Path("outputs/jev"))
    parser.add_argument("--quotes", type=Path, default=None, help="Realtime quote CSV to watch.")
    parser.add_argument("--live-quotes", action="store_true", help="Poll AkShare spot quotes.")
    parser.add_argument("--quote-interval", type=float, default=30.0)
    parser.add_argument("--poll", type=float, default=5.0, help="Seconds between artifact checks.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--export", type=Path, default=None, help="Write a static HTML snapshot and exit."
    )
    args = parser.parse_args()

    if args.export:
        snapshot = build_desk_snapshot(
            args.cycle_root,
            pnl_curve=args.pnl_curve,
            quotes=load_quotes_csv(args.quotes) if args.quotes and args.quotes.exists() else None,
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
    print(
        f"trading desk on http://{args.host}:{args.port} as_of={state.snapshot.get('as_of')}",
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


if __name__ == "__main__":
    raise SystemExit(main())
