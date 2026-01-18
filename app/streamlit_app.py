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
    title="What to watch? NBA Watchability Today",
    caption=(
        "The Watchability Index (WI) quantifies the watchability of an NBA game by combining "
        "the expected competitiveness and quality of teams playing to predict the overall quality and watchability "
        "of the basketball being played. WI also updates during live games accounting "
        "for the evolving competitiveness of the game. WI goes from 0 to 100 and is broken into Amazing, Great, Good, Ok, and Bad "
        "buckets to help users understand and contextualize the relative watchability of games. "
        "Future versions of the metric will let users personalize based on their "
        "preferences over competitiveness and team and player quality."
    ),
)
