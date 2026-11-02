"""Shared accounting snapshot; refresh never invalidates AI/OCR caches."""
import streamlit as st
from jj_closures import read_all

@st.cache_data(ttl=30,max_entries=2)
def read_ledger(_client):
    return read_all(_client,'jj_recon_records').to_dict('records'),read_all(_client,'jj_recon_links').to_dict('records')
