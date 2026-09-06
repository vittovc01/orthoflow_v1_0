import os, hashlib, hmac
import streamlit as st
from supabase import create_client

st.set_page_config(page_title='OrthoFlow 7.2 Enterprise', page_icon='🏥', layout='centered')


def secret(name, default=None):
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.getenv(name, default)


@st.cache_resource
def client():
    url = secret('SUPABASE_URL')
    key = secret('SUPABASE_SERVICE_KEY') or secret('SUPABASE_ANON_KEY') or secret('SUPABASE_KEY')
    if not url or not key:
        raise RuntimeError('Supabase non configurato nei Secrets')
    return create_client(str(url).rstrip('/'), str(key))


def password_verify(password, salt, expected_hash):
    try:
        digest = hashlib.pbkdf2_hmac(
            'sha256',
            str(password).encode('utf-8'),
            str(salt or '').encode('utf-8'),
            210_000,
        ).hex()
        return hmac.compare_digest(digest, str(expected_hash or ''))
    except Exception:
        return False


def load_user(username):
    try:
        rows = (
            client().table('utenti_app')
            .select('*')
            .eq('username', str(username).strip())
            .limit(1)
            .execute().data or []
        )
        return rows[0] if rows else None
    except Exception:
        return None


def audit_login(row):
    try:
        client().table('audit_log').insert({
            'utente': row.get('username', ''),
            'ruolo': row.get('ruolo', ''),
            'agente': row.get('agente_nome', '') or '',
            'azione': 'LOGIN',
            'tabella': 'utenti_app',
            'record_id': str(row.get('id', '')),
            'dettaglio': 'Accesso eseguito',
        }).execute()
    except Exception:
        pass


st.markdown('''
<style>
[data-testid="stHeader"] { background: transparent; }
[data-testid="stToolbar"] { display: none; }
[data-testid="stSidebar"] { display: none; }
[data-testid="collapsedControl"] { display: none; }
.block-container {
    max-width: 520px;
    padding-top: 2.2rem;
    padding-bottom: 2.5rem;
}
[data-testid="stAppViewContainer"] {
    background:
        radial-gradient(circle at 85% 12%, rgba(17, 126, 98, .12), transparent 30%),
        radial-gradient(circle at 10% 85%, rgba(17, 126, 98, .08), transparent 30%),
        linear-gradient(180deg, #f7fbfa 0%, #ffffff 48%, #f4faf8 100%);
}
.of-brand {
    text-align:center;
    margin: 1.4rem auto 1rem;
}
.of-mark {
    width:68px;
    height:68px;
    border-radius:22px;
    margin:0 auto 14px;
    display:flex;
    align-items:center;
    justify-content:center;
    color:white;
    font-size:34px;
    font-weight:800;
    background:linear-gradient(145deg,#0f766e,#15936f);
    box-shadow:0 12px 30px rgba(15,118,110,.22);
}
.of-brand h1 {
    margin:0;
    font-size:clamp(2.25rem, 9vw, 3.55rem);
    letter-spacing:-.055em;
    color:#0b2730;
    line-height:.98;
}
.of-brand .version { color:#147f68; }
.of-brand .enterprise {
    margin-top:8px;
    font-size:1rem;
    letter-spacing:.32em;
    text-transform:uppercase;
    color:#61757d;
}
.of-tagline {
    text-align:center;
    color:#51656d;
    font-size:1.03rem;
    margin:1.5rem auto 1.35rem;
    max-width:390px;
}
.of-features {
    display:grid;
    grid-template-columns:repeat(4,1fr);
    gap:8px;
    margin:0 auto 1.6rem;
}
.of-feature {
    text-align:center;
    padding:10px 4px;
    border-radius:16px;
    color:#31505a;
    font-size:.78rem;
    font-weight:650;
}
.of-feature span {
    display:block;
    font-size:1.45rem;
    margin-bottom:4px;
}
.of-login-title {
    text-align:center;
    margin:.25rem 0 .1rem;
    color:#0b2730;
    font-size:1.55rem;
    font-weight:780;
}
.of-login-sub {
    text-align:center;
    color:#6a7c83;
    margin:0 0 .9rem;
    font-size:.94rem;
}
[data-testid="stForm"] {
    background:rgba(255,255,255,.92);
    border:1px solid rgba(15,118,110,.13);
    border-radius:24px;
    padding:1.25rem 1.15rem 1.1rem;
    box-shadow:0 18px 50px rgba(27,58,63,.10);
    backdrop-filter:blur(12px);
}
.stTextInput input {
    min-height:52px;
    border-radius:14px !important;
    border:1px solid rgba(33,72,78,.15) !important;
    background:#fbfdfc !important;
}
.stButton > button, [data-testid="stFormSubmitButton"] > button {
    width:100%;
    min-height:52px;
    border-radius:14px !important;
    border:none !important;
    background:linear-gradient(135deg,#0f766e,#16966f) !important;
    color:white !important;
    font-weight:760 !important;
    font-size:1.02rem !important;
    box-shadow:0 8px 20px rgba(15,118,110,.18);
}
.of-secure {
    text-align:center;
    margin-top:1rem;
    color:#71838a;
    font-size:.82rem;
}
.of-footer {
    text-align:center;
    color:#8a9aa0;
    font-size:.76rem;
    margin-top:1.55rem;
}
@media (max-width: 600px) {
    .block-container { padding:1.1rem 1rem 2rem; }
    .of-brand { margin-top:.8rem; }
    .of-mark { width:60px; height:60px; border-radius:19px; font-size:30px; }
    .of-features { gap:2px; }
    .of-feature { font-size:.72rem; padding:8px 2px; }
}
</style>
''', unsafe_allow_html=True)

st.markdown('''
<div class="of-brand">
  <div class="of-mark">OF</div>
  <h1>Ortho<span class="version">Flow</span> 7.2</h1>
  <div class="enterprise">Enterprise</div>
</div>
<div class="of-tagline">Control Tower per logistica, magazzino e attività chirurgica ortopedica.</div>
<div class="of-features">
  <div class="of-feature"><span>📷</span>Scansiona</div>
  <div class="of-feature"><span>📦</span>Gestisci</div>
  <div class="of-feature"><span>🔎</span>Traccia</div>
  <div class="of-feature"><span>📊</span>Analizza</div>
</div>
''', unsafe_allow_html=True)

with st.form('orthoflow_login'):
    st.markdown('<div class="of-login-title">Accedi a OrthoFlow</div>', unsafe_allow_html=True)
    st.markdown('<div class="of-login-sub">Inserisci le credenziali fornite dall’amministratore.</div>', unsafe_allow_html=True)
    username = st.text_input('Nome utente', placeholder='Nome utente')
    password = st.text_input('Password', type='password', placeholder='Password')
    submitted = st.form_submit_button('🔐  Accedi', use_container_width=True)

if submitted:
    row = load_user(username)
    if row and bool(row.get('attivo', True)) and password_verify(password, row.get('password_salt'), row.get('password_hash')):
        st.session_state.user = row.get('username', username)
        st.session_state.ruolo = row.get('ruolo', 'Agente')
        st.session_state.agente_nome = row.get('agente_nome', '') or ''
        st.session_state.utente_id = row.get('id')
        try:
            client().table('utenti_app').update({'ultimo_accesso': 'now()'}).eq('id', row.get('id')).execute()
        except Exception:
            pass
        audit_login(row)
        st.rerun()
    else:
        st.error('Credenziali errate o utente disattivato.')

st.markdown('<div class="of-secure">🔒 Accesso protetto · OrthoFlow Control Tower</div>', unsafe_allow_html=True)
st.markdown('<div class="of-footer">OrthoFlow 7.2 Enterprise</div>', unsafe_allow_html=True)
