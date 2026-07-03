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

/* Sidebar — Tide surface, white nav (the one place brand color dominates).
   Color only the elements that sit on the Tide surface — a blanket
   `[data-testid="stSidebar"] *` rule bled white text into popover panels
   (light background) and made them unreadable. */
[data-testid="stSidebar"] { background-color: var(--surface-sidebar); }
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"],
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] li,
[data-testid="stSidebar"] [data-testid="stCaptionContainer"],
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] *,
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] *,
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3,
[data-testid="stSidebar"] .stRadio label p, [data-testid="stSidebar"] .stRadio label span,
[data-testid="stSidebar"] .stButton > button { color: #ffffff; }
/* anything rendered on a light panel inside the sidebar stays dark */
[data-testid="stSidebar"] [data-testid="stPopoverBody"],
[data-testid="stSidebar"] [data-testid="stPopoverBody"] * { color: var(--color-ink) !important; }

/* App name — Fraunces, per the design system (the one place it appears in the sidebar).
   A plain div, not a markdown h3: Streamlit's element container under-sizes an h3
   in the sidebar and the next block overlaps it. */
.console-brand {
  font-family: var(--font-display); font-weight: 600; font-size: 1.15rem;
  color: #ffffff; padding: 0 0 8px 4px;
}
/* keep the brand header clear of the sidebar's collapse-control strip */
[data-testid="stSidebarUserContent"] { padding-top: 4rem; }

/* Tighter nav rhythm: Streamlit's default 1rem block gap reads as scattered buttons */
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 0.3rem; }

/* Group captions as section labels (11px, tracked, dimmed — DESIGN-pronatura sidebar spec) */
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
  font-size: 11px; letter-spacing: 0.08em; opacity: 0.6; margin-top: 8px;
}

/* Sidebar nav buttons: quiet by default, active = darker fill + amber edge
   (the only warm element on the cool surface, per the design system). */
[data-testid="stSidebar"] .stButton > button {
  justify-content: flex-start; text-align: left; font-weight: 500;
}
/* the button's inner wrapper centers content by default — left-align it */
[data-testid="stSidebar"] .stButton > button > div {
  justify-content: flex-start; width: 100%;
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
