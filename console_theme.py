"""Pronatura Noroeste design system for the Streamlit console (Dashboard Extension).
config.toml sets the base palette (Tide primary, Shell bg, Canvas surfaces, Ink text);
this injects the brand fonts + the pieces config can't reach (Tide sidebar, Fraunces
page titles, near-flat radii). See Planning/DESIGN-pronatura.md.
"""
import streamlit as st

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&family=Fraunces:opsz,wght@9..144,400;9..144,600&display=swap');

/* Body & UI face — DM Sans */
html, body, [class*="css"], button, input, textarea, select,
.stMarkdown, [data-testid="stMetricValue"], [data-testid="stMetricLabel"] {
  font-family: 'DM Sans', 'Helvetica Neue', Arial, sans-serif;
}

/* Page titles (H1) — Fraunces, in Tide */
.stApp h1 { font-family: 'Fraunces', Georgia, serif; font-weight: 600; color: #1b5c5a; letter-spacing: -0.005em; }
.stApp h2, .stApp h3 { font-weight: 600; color: #1e1c19; }

/* Sidebar — Tide surface, white nav (the one place brand color dominates) */
[data-testid="stSidebar"] { background-color: #1b5c5a; }
[data-testid="stSidebar"] * { color: #ffffff !important; }
[data-testid="stSidebar"] .stButton > button {
  background-color: #164d4b; border: 1px solid rgba(255,255,255,0.25); color: #ffffff;
}

/* Near-flat radii — a field organization, not a fintech app */
.stButton > button, .stDownloadButton > button,
[data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="textarea"] { border-radius: 4px; }
[data-testid="stForm"], [data-testid="stExpander"] { border-radius: 6px; border-color: #e8e4df; }

/* Buttons — semibold, sentence case */
.stButton > button, .stDownloadButton > button { font-weight: 600; }
</style>
"""


def apply_theme():
    st.markdown(_CSS, unsafe_allow_html=True)
