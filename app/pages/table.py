from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import streamlit as st

from app.dashboard_views import inject_minimal_chrome_css, render_table_page


st.set_page_config(page_title="table", layout="wide", initial_sidebar_state="collapsed")
inject_minimal_chrome_css()
render_table_page()

