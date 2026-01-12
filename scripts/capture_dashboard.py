from playwright.sync_api import sync_playwright
from pathlib import Path
from PIL import Image
import time

DASHBOARD_URL = "https://nba-watchability.streamlit.app/?mode=twitter"
OUT_DIR = Path("output")
FULL_IMG = OUT_DIR / "full.png"
CROPPED_IMG = OUT_DIR / "dashboard.png"

def capture_dashboard():
    print("Starting screenshot capture...")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        context = browser.new_context(
            viewport={"width": 1600, "height": 1000},
            device_scale_factor=2.5,  # 🔥 sharp
        )
        page = context.new_page()

        page.goto(DASHBOARD_URL, timeout=60_000)
        page.wait_for_load_state("networkidle", timeout=60_000)
        time.sleep(6)  # allow Altair + logos to render

        page.screenshot(path=str(FULL_IMG), full_page=False)
        browser.close()

    # --- Crop left side (chart area) ---
    img = Image.open(FULL_IMG)
    width, height = img.size

    # Crop ~left 58% of screen (tweak if needed)
    crop_box = (0, 0, int(width * 0.58), height)
    cropped = img.crop(crop_box)
    cropped.save(CROPPED_IMG)

    print(f"Saved cropped dashboard to {CROPPED_IMG}")
    return CROPPED_IMG