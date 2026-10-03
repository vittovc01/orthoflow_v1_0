"""Local browser regression harness: real branding, no credentials or database."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import streamlit as st
from orthoflow_branding import configure_page


def home():
    configure_page(page_title="OrthoFlow CI", layout="wide", initial_sidebar_state="collapsed")
    st.title("OrthoFlow CI")


def scarico():
    configure_page(page_title="Scarico CI", layout="wide")
    st.title("Scarico Sala AI CI")


st.navigation([
    st.Page(home, title="Home", icon="🏠", default=True),
    st.Page(scarico, title="Scarico Sala AI", icon="📸"),
], position="sidebar", expanded=True).run()

