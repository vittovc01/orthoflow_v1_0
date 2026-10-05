"""Existing business workflows inside OrthoFlow, using the app's session."""
import os
import runpy

import streamlit as st
from supabase import create_client
from fastapi import HTTPException
from mobile.access import COOKIE, office_identity


def bootstrap(backend=None):
    token = st.context.cookies.get(COOKIE, '')
    try:
        backend = backend or create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
        row = office_identity(token, backend)
    except (HTTPException, KeyError):
        st.session_state.clear()
        st.error('Accesso scaduto. Torna all’app ed effettua nuovamente l’accesso.')
        st.stop()
    # Refreshed on every rerun, including after a director changes permissions.
    st.session_state.update(user=row['username'], ruolo='Admin' if 'DIREZIONE' in (row.get('permessi') or []) else row['ruolo'],
        permessi=row.get('permessi') or [], agente_nome=row.get('agente_nome') or '',
        utente_id=row['id'], office_runtime=True)
    return row


if __name__ == '__main__':
    bootstrap()
    runpy.run_path('app.py', run_name='__main__')
