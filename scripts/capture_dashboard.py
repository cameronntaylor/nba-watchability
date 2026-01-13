from playwright.sync_api import sync_playwright
from pathlib import Path
import time

APP_BASE_URL = "https://nba-watchability.streamlit.app"
CHART_URL = f"{APP_BASE_URL}/chart?embed=true"
TABLE_URL = f"{APP_BASE_URL}/table?embed=true"

OUT_DIR = Path("output")
CHART_IMG = OUT_DIR / "chart.png"
TABLE_IMG = OUT_DIR / "table.png"


def _capture(url: str, out_path: Path, full_page: bool) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1600, "height": 1000},
            device_scale_factor=2.0,
        )
        page = context.new_page()
        page.goto(url, timeout=60_000)
        page.wait_for_load_state("networkidle", timeout=60_000)
        time.sleep(6)  # allow Altair + logos to render
        page.screenshot(path=str(out_path), full_page=full_page)
        browser.close()


def capture_dashboard():
    print("Starting screenshot capture...")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    _capture(CHART_URL, CHART_IMG, full_page=False)
    _capture(TABLE_URL, TABLE_IMG, full_page=True)

    print(f"Saved chart screenshot to {CHART_IMG}")
    print(f"Saved table screenshot to {TABLE_IMG}")
    return [CHART_IMG, TABLE_IMG]
