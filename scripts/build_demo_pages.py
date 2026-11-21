"""Build a self-contained static GitHub Pages demo site (Trading Desk + Stock Picker).

Uses synthetic CSI 300 sample data from ``demo_fixtures`` and zero third-party dependencies so
GitHub Actions can publish an interactive preview directly from the standard library.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.reports.demo_fixtures import (  # noqa: E402
    build_demo_workspace,
    demo_jev_payload,
    demo_research_payload,
)
from fintech_quant.reports.desk import build_desk_snapshot, render_desk_html  # noqa: E402
from fintech_quant.reports.picker import (  # noqa: E402
    load_picker_data,
    picks_payload,
    stock_payload,
    universe_payload,
)

PICKER_TEMPLATE = SRC / "fintech_quant" / "reports" / "picker_template.html"

DEMO_BANNER_HTML = (
    '<div style="background:#161b22;color:#c9d1d9;border-bottom:1px solid #30363d;'
    'padding:8px 16px;font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;'
    'display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap">'
    '<span><strong>STATIC DEMO</strong> · Synthetic CSI 300 sample data (read-only preview) · '
    'Run locally: <code>python scripts/serve_trading_desk.py --demo</code></span>'
    '<a href="https://github.com/Yakou207/Vibe-Trading" '
    'style="color:#58a6ff;text-decoration:none" target="_blank" rel="noopener">'
    'GitHub Repo ↗</a></div>'
)


def _static_fetch_shim(bundle: dict[str, object]) -> str:
    payload = json.dumps(bundle, ensure_ascii=False, separators=(",", ":")).replace(
        "<", "\\u003c"
    )
    return (
        f'<script type="application/json" id="static-demo-bundle">{payload}</script>\n'
        "<script>\n"
        "(function(){\n"
        "  const B = JSON.parse(document.getElementById('static-demo-bundle').textContent);\n"
        "  const origFetch = window.fetch.bind(window);\n"
        "  function resolveSym(q){\n"
        "    const s = String(q || '').trim().toUpperCase();\n"
        "    if (!s) return null;\n"
        "    if (B.stocks[s]) return s;\n"
        "    for (const sym of Object.keys(B.stocks)) {\n"
        "      const item = B.stocks[sym];\n"
        "      const bare = sym.split('.')[0];\n"
        "      if (bare === s || (item.name && item.name.includes(q.trim()))) return sym;\n"
        "    }\n"
        "    return null;\n"
        "  }\n"
        "  function jsonResp(obj){\n"
        "    return Promise.resolve(new Response(JSON.stringify(obj), {\n"
        "      status: 200, headers: { 'Content-Type': 'application/json; charset=utf-8' }\n"
        "    }));\n"
        "  }\n"
        "  window.fetch = function(input, init){\n"
        "    const raw = typeof input === 'string' ? input : (input && input.url) || '';\n"
        "    if (!raw.startsWith('/api/')) return origFetch(input, init);\n"
        "    const u = new URL(raw, 'http://demo.local');\n"
        "    const p = u.pathname;\n"
        "    const q = u.searchParams.get('q') || '';\n"
        "    if (p === '/api/universe') return jsonResp(B.universe);\n"
        "    if (p === '/api/picks') return jsonResp(B.picks);\n"
        "    if (p === '/api/intraday-monitor') return jsonResp(null);\n"
        "    if (p === '/api/intraday') return jsonResp({error: '静态 Demo 不包含盘中分时行情'});\n"
        "    if (p === '/api/events_llm') return jsonResp({error: '静态 Demo 不调用外部 LLM API'});\n"
        "    const sym = resolveSym(q);\n"
        "    if (p === '/api/stock') return jsonResp(sym ? B.stocks[sym] : {error: 'Demo 仅包含 10 只样例股，未找到：' + q});\n"
        "    if (p === '/api/research') return jsonResp(sym ? B.research[sym] : {error: 'Demo 未找到：' + q});\n"
        "    if (p === '/api/jev') return jsonResp(sym ? B.jev[sym] : {error: 'Demo 未找到：' + q});\n"
        "    return jsonResp({error: 'Unsupported demo endpoint: ' + p});\n"
        "  };\n"
        "})();\n"
        "</script>"
    )


def build_demo_pages(output_dir: Path) -> list[Path]:
    """Generate ``index.html``, ``picks.html`` and ``.nojekyll`` into ``output_dir``."""
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vibe-trading-pages-") as tmp:
        demo = build_demo_workspace(Path(tmp))
        snapshot = build_desk_snapshot(
            demo.cycle_root,
            pnl_curve=demo.pnl_curve,
            quotes_status="demo",
        )
        desk_html = render_desk_html(snapshot, live=False)
        desk_html = desk_html.replace(
            '<nav class="nav" id="nav" hidden><a href="/" aria-current="page">交易桌</a><a href="/picks">选股</a></nav>',
            '<nav class="nav" id="nav"><a href="./index.html" aria-current="page">交易桌</a><a href="./picks.html">选股</a></nav>',
        )
        desk_html = desk_html.replace("<body>", f"<body>\n{DEMO_BANNER_HTML}", 1)

        picker_data = load_picker_data(demo.state)
        pool_state = json.loads((demo.pool_root / "state.json").read_text(encoding="utf-8"))
        pool_v2_state = json.loads((demo.pool_v2_root / "state.json").read_text(encoding="utf-8"))
        scoring_v2 = json.loads(demo.scoring_v2.read_text(encoding="utf-8"))

        stocks_map: dict[str, object] = {}
        research_map: dict[str, object] = {}
        jev_map: dict[str, object] = {}
        for symbol in sorted(picker_data.members):
            stocks_map[symbol] = stock_payload(
                picker_data, symbol, live=None, scoring_v2=scoring_v2, fresh=False
            )
            research_map[symbol] = demo_research_payload(picker_data, symbol)
            jev_map[symbol] = demo_jev_payload(picker_data, symbol)

        bundle: dict[str, object] = {
            "universe": universe_payload(picker_data, live=None),
            "picks": picks_payload(picker_data, pool_state, pool_v2_state),
            "stocks": stocks_map,
            "research": research_map,
            "jev": jev_map,
        }

        picker_html = PICKER_TEMPLATE.read_text(encoding="utf-8").replace(
            "__PICKER_TITLE__", html.escape(f"选股 Demo · CSI 300 · {picker_data.as_of}")
        )
        picker_html = picker_html.replace(
            '<nav class="nav"><a href="/">交易桌</a><a href="/picks" aria-current="page">选股</a></nav>',
            '<nav class="nav"><a href="./index.html">交易桌</a><a href="./picks.html" aria-current="page">选股</a></nav>',
        )
        picker_html = picker_html.replace("<body>", f"<body>\n{DEMO_BANNER_HTML}", 1)
        picker_html = picker_html.replace("</head>", f"{_static_fetch_shim(bundle)}\n</head>", 1)

    index_path = output_dir / "index.html"
    picks_path = output_dir / "picks.html"
    nojekyll_path = output_dir / ".nojekyll"
    index_path.write_text(desk_html, encoding="utf-8")
    picks_path.write_text(picker_html, encoding="utf-8")
    nojekyll_path.write_text("", encoding="utf-8")
    return [index_path, picks_path, nojekyll_path]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build static GitHub Pages demo site.")
    parser.add_argument("--output", type=Path, default=ROOT / "_site")
    args = parser.parse_args()
    written = build_demo_pages(args.output)
    for path in written:
        print(f"wrote {path} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
