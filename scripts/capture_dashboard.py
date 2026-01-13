from pathlib import Path
import os
import time

from PIL import Image
from playwright.sync_api import sync_playwright


DASHBOARD_URL = os.getenv(
    "DASHBOARD_URL", "https://nba-watchability.streamlit.app/?mode=twitter"
)

OUT_DIR = Path("output")
FULL_IMG = OUT_DIR / "full.png"
CHART_IMG = OUT_DIR / "chart.png"
TABLE_IMG = OUT_DIR / "table.png"

# --- Chart crop (historical defaults) ---
CHART_LEFT_PAD = int(os.getenv("CHART_LEFT_PAD", "125"))
CHART_TOP_PAD = int(os.getenv("CHART_TOP_PAD", "775"))
CHART_RIGHT_PAD = int(os.getenv("CHART_RIGHT_PAD", "1900"))
CHART_BOTTOM_PAD = int(os.getenv("CHART_BOTTOM_PAD", "250"))

# --- Table crop (tweak as needed) ---
TABLE_LEFT_PAD = int(os.getenv("TABLE_LEFT_PAD", "2000"))
TABLE_TOP_PAD = int(os.getenv("TABLE_TOP_PAD", "760"))
TABLE_RIGHT_PAD = int(os.getenv("TABLE_RIGHT_PAD", "125"))
TABLE_BOTTOM_PAD = int(os.getenv("TABLE_BOTTOM_PAD", "250"))


def capture_dashboard():
    print("Starting screenshot capture...")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1600, "height": 1000},
            device_scale_factor=2.5,  # sharp
        )
        page = context.new_page()

        page.goto(DASHBOARD_URL, timeout=60_000)
        page.wait_for_load_state("networkidle", timeout=60_000)
        time.sleep(6)  # allow Altair + logos to render

        page.screenshot(path=str(FULL_IMG), full_page=False)
        browser.close()

    img = Image.open(FULL_IMG)
    width, height = img.size

    # --- Crop left side (chart area) ---
    chart_box = (
        CHART_LEFT_PAD,
        CHART_TOP_PAD,
        width - CHART_RIGHT_PAD,
        height - CHART_BOTTOM_PAD,
    )
    img.crop(chart_box).save(CHART_IMG)

    # --- Crop right side (table area) ---
    table_box = (
        TABLE_LEFT_PAD,
        TABLE_TOP_PAD,
        width - TABLE_RIGHT_PAD,
        height - TABLE_BOTTOM_PAD,
    )
    img.crop(table_box).save(TABLE_IMG)

    print(f"Saved chart screenshot to {CHART_IMG}")
    print(f"Saved table screenshot to {TABLE_IMG}")
    return [CHART_IMG, TABLE_IMG]
