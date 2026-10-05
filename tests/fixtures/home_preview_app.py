"""Actual Home page with visibly synthetic data, for browser layout verification."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import streamlit as st
import supabase
from tests.fixtures.home_backend import HomeBackend
supabase.create_client=lambda *args,**kwargs:HomeBackend()
st.secrets={'SUPABASE_URL':'http://127.0.0.1:1','SUPABASE_SERVICE_KEY':'ci-dummy-key'}
st.session_state['user']='Demo'
st.session_state['ruolo']='Admin'
st.session_state['permessi']=['DIREZIONE']
root=Path(__file__).resolve().parents[2]
names=[('pages/00_Control_Tower.py','Home'),('pages/05_Scarico_Sala_AI.py','Scarico sala'),('pages/04_DDT_Carico_v2.py','DDT'),('pages/06_Gestione_Interventi.py','Interventi'),('pages/09_Corrieri.py','Corrieri'),('pages/14_Anomalie_Prezzi.py','Anomalie'),('pages/01_WMS.py','Magazzino')]
st.navigation([st.Page(str(root/path),title=label,default=i==0) for i,(path,label) in enumerate(names)],expanded=True).run()
