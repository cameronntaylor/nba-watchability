from playwright.sync_api import sync_playwright
import time
from pathlib import Path

DASHBOARD_URL = "https://nba-watchability.streamlit.app/?mode=twitter"
OUT_PATH = Path("output/dashboard.png")

def capture_dashboard():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 1400, "height": 900}
        )

        page.goto(DASHBOARD_URL, timeout=60_000)

        # Wait for your title to appear
        page.wait_for_selector("text=NBA Watchability", timeout=60_000)
        time.sleep(3)  # allow charts to fully render

        page.screenshot(path=str(OUT_PATH), full_page=False)
        browser.close()

    return OUT_PATH