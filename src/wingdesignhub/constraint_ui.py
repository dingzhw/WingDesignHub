"""User-facing units and four-state labels; leave stored engineering values intact."""
import streamlit as st
from .presentation import constraint_rows


def render(summary,p=None):
    st.dataframe(constraint_rows(summary,p),hide_index=True)
