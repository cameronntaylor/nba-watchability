from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import streamlit as st

from app.dashboard_views import render_full_dashboard

st.set_page_config(page_title="NBA Watchability (WI)", layout="wide", initial_sidebar_state="collapsed")

render_full_dashboard(
    title="NBA Watchability Today",
    caption=(
        "NBA Watchability ranks tonight’s games by how worth watching they are, "
        "using expected closeness + team quality (injury-adjusted)."
    ),
)
