from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESK_HTML = ROOT / "src" / "fintech_quant" / "reports" / "desk_template.html"
PICKER_HTML = ROOT / "src" / "fintech_quant" / "reports" / "picker_template.html"


def test_desk_and_picker_share_theme_key_anti_flash_and_toggle() -> None:
    desk = DESK_HTML.read_text(encoding="utf-8")
    picker = PICKER_HTML.read_text(encoding="utf-8")

    for name, html in (("desk", desk), ("picker", picker)):
        head = html.split("</head>", 1)[0]
        assert 'localStorage.getItem("vibe_theme")' in head, f"{name} missing anti-flash head script"
        assert 'document.documentElement.dataset.theme=t' in head, f"{name} missing dataset.theme init"
        assert 'id="theme-toggle"' in html, f"{name} missing theme toggle button"
        assert ':root[data-theme="light"]' in html, f"{name} missing explicit light theme tokens"
        assert 'window.addEventListener("storage"' in html, f"{name} missing cross-tab theme sync"
        assert "prefers-reduced-motion: reduce" in html, f"{name} missing reduced-motion support"
        assert "padding: 16px 20px 40px" in html, f"{name} container padding mismatch"

    # Desk theme toggle must repaint both Chart.js and Pixel-Office canvas.
    assert "renderCurve();" in desk
    assert "drawOfficeFrame();" in desk


def test_picker_has_shimmer_skeleton_and_loading_states() -> None:
    picker = PICKER_HTML.read_text(encoding="utf-8")

    assert 'id="analyze-btn"' in picker
    assert "renderStockSkeleton" in picker
    assert 'id="stock-load-timer"' in picker
    assert 'id="research-load-timer"' in picker
    assert "@keyframes vibe-shimmer" in picker
    assert "@keyframes vibe-spin" in picker
    assert "setAnalyzeBusy(true)" in picker
    assert "setAnalyzeBusy(false)" in picker
