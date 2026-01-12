import os
import time
from pathlib import Path

USE_PLAYWRIGHT = os.getenv("USE_PLAYWRIGHT", "false").lower() == "true"

DASHBOARD_URL = "https://nba-watchability.streamlit.app/?mode=twitter"
OUT_PATH = Path("output/dashboard.png")


def capture_dashboard():
    print("Starting screenshot capture...")

    if not USE_PLAYWRIGHT:
        print("Playwright disabled (local dry run). Skipping screenshot.")
        return None

    # IMPORTANT: lazy import (no indentation before this line)
    from playwright.sync_api import sync_playwright

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        page = browser.new_page(
            viewport={"width": 1400, "height": 900}
        )

        page.goto(DASHBOARD_URL, timeout=60_000)

        # Wait for a stable element
        page.wait_for_selector("#dashboard-root", timeout=60_000)
        time.sleep(8)

        page.screenshot(
            path=str(OUT_PATH),
            full_page=False
        )

        browser.close()

    print(f"Screenshot saved to {OUT_PATH}")
    return OUT_PATH