"""Pronatura Noroeste design system for the Streamlit console (Dashboard Extension).
config.toml sets the base palette (Tide primary, Shell bg, Canvas surfaces, Ink text);
this injects the brand fonts + the pieces config can't reach (Tide sidebar, Fraunces
page titles, near-flat radii, active-nav highlight). All values come from the tokens
in Planning/DESIGN-pronatura.md — change them in :root, not inline.
"""
import streamlit as st

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&family=Fraunces:opsz,wght@9..144,400;9..144,600&display=swap');

:root {
  /* Colors — DESIGN-pronatura.md tokens */
  --color-tide: #1b5c5a;
  --color-mangrove: #0f3634;
  --color-kelp: #2e7b78;
  --color-amber: #e07c2a;
  --color-fog: #e8e4df;
  --color-ink: #1e1c19;
  --surface-sidebar: #1b5c5a;
  --surface-sidebar-active: #164d4b;

  /* Typography — system fallbacks keep the console readable offline */
  --font-sans: 'DM Sans', 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
  --font-display: 'Fraunces', Georgia, 'Times New Roman', serif;

  /* Shapes — near-flat: a field organization, not a fintech app */
  --radius-button: 4px;
  --radius-card: 6px;
}

/* Body & UI face — DM Sans */
html, body, [class*="css"], button, input, textarea, select,
.stMarkdown, [data-testid="stMetricValue"], [data-testid="stMetricLabel"] {
  font-family: var(--font-sans);
}

/* Page titles (H1) — Fraunces, in Tide */
.stApp h1 { font-family: var(--font-display); font-weight: 600; color: var(--color-tide); letter-spacing: -0.005em; }
.stApp h2, .stApp h3 { font-weight: 600; color: var(--color-ink); }

/* Sidebar — Tide surface, white nav (the one place brand color dominates) */
[data-testid="stSidebar"] { background-color: var(--surface-sidebar); }
[data-testid="stSidebar"] * { color: #ffffff !important; }

/* Sidebar nav buttons: quiet by default, active = darker fill + amber edge
   (the only warm element on the cool surface, per the design system). */
[data-testid="stSidebar"] .stButton > button {
  justify-content: flex-start; text-align: left; font-weight: 500;
}
[data-testid="stSidebar"] .stButton > button[kind="secondary"] {
  background-color: transparent; border: 1px solid transparent; opacity: 0.85;
}
[data-testid="stSidebar"] .stButton > button[kind="secondary"]:hover {
  background-color: var(--surface-sidebar-active); opacity: 1;
  border-color: rgba(255,255,255,0.25);
}
[data-testid="stSidebar"] .stButton > button[kind="primary"] {
  background-color: var(--surface-sidebar-active);
  border: 1px solid rgba(255,255,255,0.25);
  border-left: 3px solid var(--color-amber);
  font-weight: 600;
}

/* Near-flat radii */
.stButton > button, .stDownloadButton > button,
[data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="textarea"] { border-radius: var(--radius-button); }
[data-testid="stForm"], [data-testid="stExpander"] { border-radius: var(--radius-card); border-color: var(--color-fog); }

/* Buttons — semibold, sentence case */
.stButton > button, .stDownloadButton > button { font-weight: 600; }
</style>
"""


def apply_theme():
    st.markdown(_CSS, unsafe_allow_html=True)
