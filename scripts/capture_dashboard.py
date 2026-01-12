from playwright.sync_api import sync_playwright
from pathlib import Path
import time

DASHBOARD_URL = "https://nba-watchability.streamlit.app/?mode=twitter"
OUT_PATH = Path("output/dashboard.png")

def capture_dashboard():
    print("Starting screenshot capture...")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # set device_scale_factor for sharp images
        context = browser.new_context(
            viewport={"width": 1600, "height": 1000},
            device_scale_factor=2.5,  # 🔥 higher = sharper
        )
        page = context.new_page()

        page.goto(DASHBOARD_URL, timeout=60_000)

        # Wait until Streamlit finishes loading data + charts
        page.wait_for_load_state("networkidle", timeout=60_000)
        time.sleep(6)  # buffer for Altair rendering

        # Screenshot the first Vega-Lite chart (the left plot)
        chart = page.locator('div[data-testid="stVegaLiteChart"]').first
        chart.wait_for(state="visible", timeout=60_000)
        chart.screenshot(path=str(OUT_PATH))

        browser.close()

    return OUT_PATH