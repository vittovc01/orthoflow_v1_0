import os, re, hashlib, hmac, secrets
from datetime import date
from pathlib import Path
import pandas as pd
import streamlit as st
from supabase import create_client

try:
    from ai_ocr import ai_enabled, analyze_image, normalize_ai_items
except Exception:
    ai_enabled=lambda: False
    analyze_image=None
    normalize_ai_items=lambda x: []

st.set_page_config(page_title='OrthoFlow 7.2 Enterprise', layout='wide')


st.markdown("""
<style>
:root {
    --of-primary: #176b57;
    --of-primary-soft: rgba(23,107,87,.10);
    --of-border: rgba(49,51,63,.13);
}
[data-testid="stAppViewContainer"] {
    background: linear-gradient(180deg, rgba(23,107,87,.035) 0, transparent 260px);
}
[data-testid="stSidebar"] {
    border-right: 1px solid var(--of-border);
}
[data-testid="stSidebar"] > div:first-child {
    padding-top: 1.4rem;
}
.block-container {
    max-width: 1500px;
    padding-top: 1.6rem;
    padding-bottom: 3rem;
}
h1, h2, h3 { letter-spacing: -.025em; }
h1 { font-weight: 760 !important; }
[data-testid="stMetric"] {
    background: var(--of-primary-soft);
    border: 1px solid rgba(23,107,87,.16);
    border-radius: 18px;
    padding: 16px 18px;
    min-height: 112px;
}
[data-testid="stMetricLabel"] { font-weight: 650; }
[data-testid="stMetricValue"] { font-weight: 760; }
.stButton > button, .stDownloadButton > button, .stLinkButton > a {
    border-radius: 12px !important;
    min-height: 42px;
    font-weight: 650;
}
div[data-baseweb="select"] > div,
.stTextInput input,
.stNumberInput input,
.stTextArea textarea,
.stDateInput input {
    border-radius: 12px !important;
}
[data-testid="stDataFrame"] {
    border: 1px solid var(--of-border);
    border-radius: 16px;
    overflow: hidden;
}
[data-testid="stExpander"] {
    border-radius: 14px !important;
    border-color: var(--of-border) !important;
}
.of-hero {
    padding: 20px 22px;
    border: 1px solid rgba(23,107,87,.17);
    border-radius: 20px;
    background: linear-gradient(135deg, rgba(23,107,87,.14), rgba(23,107,87,.035));
    margin-bottom: 18px;
}
.of-hero h2 { margin: 0 0 4px 0; }
.of-muted { opacity: .72; }
@media (max-width: 760px) {
    .block-container { padding: 1rem .8rem 2rem; }
    [data-testid="stMetric"] { min-height: 96px; padding: 13px; }
    .of-hero { padding: 16px; }
}
</style>
""", unsafe_allow_html=True)

def secret(name, default=None):
    try:
        if name in st.secrets: return st.secrets[name]
    except Exception: pass
    return os.getenv(name, default)

@st.cache_resource
def client():
    url=secret('SUPABASE_URL')
    key=secret('SUPABASE_SERVICE_KEY') or secret('SUPABASE_ANON_KEY') or secret('SUPABASE_KEY')
    if not url or not key: raise RuntimeError('Supabase non configurato nei Secrets')
    return create_client(str(url).rstrip('/'), str(key))

def sb(): return client()

def password_hash(password, salt=None):
    """PBKDF2-HMAC-SHA256: le password non vengono salvate in chiaro."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        str(password).encode("utf-8"),
        salt.encode("utf-8"),
        210_000,
    ).hex()
    return salt, digest

def password_verify(password, salt, expected_hash):
    try:
        _, actual_hash = password_hash(password, salt)
        return hmac.compare_digest(actual_hash, str(expected_hash or ""))
    except Exception:
        return False

def audit_log(azione, tabella="", record_id="", dettaglio=""):
    payload = {
        "utente": st.session_state.get("user", ""),
        "ruolo": st.session_state.get("ruolo", ""),
        "agente": st.session_state.get("agente_nome", ""),
        "azione": str(azione or ""),
        "tabella": str(tabella or ""),
        "record_id": str(record_id or ""),
        "dettaglio": str(dettaglio or ""),
    }
    try:
        sb().table("audit_log").insert(payload).execute()
    except Exception:
        pass

def load_user(username):
    try:
        rows = (
            sb().table("utenti_app")
            .select("*")
            .eq("username", str(username).strip())
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0] if rows else None
    except Exception:
        return None

def login_user(username, password):
    row = load_user(username)
    if not row or not bool(row.get("attivo", True)):
        return None
    if not password_verify(password, row.get("password_salt"), row.get("password_hash")):
        return None
    return row

def current_role():
    return str(st.session_state.get("ruolo", "")).strip()

def current_agent():
    return str(st.session_state.get("agente_nome", "")).strip()

def is_admin():
    return current_role() == "Admin"

def agent_filter_dataframe(data):
    """Impedisce a un agente di vedere righe intestate ad altri agenti."""
    if data is None or data.empty or current_role() != "Agente":
        return data
    agente = current_agent()
    if not agente:
        return data.iloc[0:0]
    if "agente" in data.columns:
        return data[data["agente"].astype(str).str.casefold() == agente.casefold()]
    return data

def safe_agenti_opts():
    if current_role() == "Agente":
        return [current_agent()] if current_agent() else [""]
    return agenti_opts()

@st.cache_data(ttl=120)
def df(table, order='id', desc=False):
    try:
        data = pd.DataFrame(
            sb().table(table).select('*').order(order, desc=desc).execute().data or []
        )
        return agent_filter_dataframe(data)
    except Exception as e:
        st.error(f'Errore {table}: {e}')
        return pd.DataFrame()
def ins(table, data):
    row = sb().table(table).insert(data).execute().data[0]
    audit_log("CREAZIONE", table, row.get("id",""), "Nuovo record")
    return row
def ins_safe(table, data):
    try:
        res = sb().table(table).insert(data).execute().data
        return res[0] if res else None
    except Exception as e:
        st.warning(f'Avviso: impossibile salvare su {table}: {e}')
        return None
def upsert(table, data, conflict): return sb().table(table).upsert(data, on_conflict=conflict).execute()
def upd(table, row_id, data):
    res = sb().table(table).update(data).eq('id', row_id).execute()
    audit_log("MODIFICA", table, row_id, ", ".join(data.keys()))
    return res

def dele(table, row_id):
    res = sb().table(table).delete().eq('id', row_id).execute()
    audit_log("ELIMINAZIONE", table, row_id, "Record eliminato")
    return res

def cast_like(value, old):
    if value == '':
        return None
    try:
        if isinstance(old, int):
            return int(float(value))
        if isinstance(old, float):
            return float(value)
    except Exception:
        return value
    return value

def agenti_opts():
    nomi = []
    try:
        a = df('agenti', 'nome')
        if not a.empty and 'nome' in a.columns:
            nomi += [str(x).strip() for x in a['nome'].dropna().tolist() if str(x).strip()]
    except Exception:
        pass
    try:
        i = df('interventi', 'id', True)
        if not i.empty and 'agente' in i.columns:
            nomi += [str(x).strip() for x in i['agente'].dropna().tolist() if str(x).strip()]
    except Exception:
        pass
    nomi = sorted(list(dict.fromkeys(nomi)))
    return nomi or ['']


def chunks(items, size=500):
    for i in range(0, len(items), size):
        yield items[i:i+size]

def batch_insert(table, rows, size=500):
    rows = [r for r in rows if r]
    done = 0
    for ch in chunks(rows, size):
        sb().table(table).insert(ch).execute()
        done += len(ch)
    return done

def batch_upsert(table, rows, conflict, size=500):
    rows = [r for r in rows if r]
    done = 0
    for ch in chunks(rows, size):
        sb().table(table).upsert(ch, on_conflict=conflict).execute()
        done += len(ch)
    return done

def svuota_tabella(tab):
    all_ids = sb().table(tab).select("id").execute().data or []
    ids = [x["id"] for x in all_ids if "id" in x]
    for chunk_ids in chunks(ids, 500):
        sb().table(tab).delete().in_("id", chunk_ids).execute()
    return len(ids)

def storage_upload_file(local_path, storage_path, bucket="orthoflow-impianti"):
    try:
        data = Path(local_path).read_bytes()
        try:
            sb().storage.from_(bucket).upload(storage_path, data, file_options={"upsert": "true"})
        except Exception:
            sb().storage.from_(bucket).update(storage_path, data, file_options={"upsert": "true"})
        return True
    except Exception as e:
        st.warning(f"Storage non disponibile: {e}")
        return False

def storage_signed_url(storage_path, bucket="orthoflow-impianti", expires=3600):
    try:
        res = sb().storage.from_(bucket).create_signed_url(storage_path, expires)
        if isinstance(res, dict):
            return res.get("signedURL") or res.get("signedUrl") or res.get("signed_url")
        return getattr(res, "signed_url", None) or getattr(res, "signedURL", None)
    except Exception:
        return None

def storage_delete_file(storage_path, bucket="orthoflow-impianti"):
    if not storage_path:
        return True
    try:
        sb().storage.from_(bucket).remove([str(storage_path)])
        return True
    except Exception as e:
        st.warning(f"Record eliminato, ma il file Storage non è stato rimosso: {e}")
        return False

def salva_file_locale(upload, categoria="impianti"):
    base = Path("uploads") / categoria
    base.mkdir(parents=True, exist_ok=True)
    safe_name = upload.name.replace("/", "_").replace("\\", "_")
    p = base / f"{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}_{safe_name}"
    p.write_bytes(upload.getbuffer())
    return str(p)

def salva_documento_impianto(intervento_id, file_path, nome_file, tipo_file, codice_cliente="", cliente="", agente="", data_intervento=None, cartella_clinica="", note=""):
    year = pd.Timestamp.now().strftime("%Y")
    month = pd.Timestamp.now().strftime("%m")
    safe_name = str(nome_file or Path(file_path).name).replace("/", "_").replace("\\", "_")
    storage_path = f"impianti/{year}/{month}/intervento_{intervento_id}_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}_{safe_name}"
    uploaded = storage_upload_file(file_path, storage_path)
    return ins_safe("documenti_impianto", {
        "intervento_id": str(intervento_id or ""),
        "data_intervento": str(data_intervento) if data_intervento else None,
        "codice_cliente": codice_cliente or "",
        "cliente": cliente or "",
        "agente": agente or "",
        "cartella_clinica": cartella_clinica or "",
        "nome_file": nome_file or "",
        "tipo_file": tipo_file or "",
        "percorso_file": file_path or "",
        "storage_bucket": "orthoflow-impianti" if uploaded else "",
        "storage_path": storage_path if uploaded else "",
        "note": note or "",
    })

def svuota_giacenza(codice_magazzino, origine=None):
    q = sb().table("giacenze").delete().eq("codice_magazzino", codice_magazzino)
    if origine:
        q = q.eq("origine", origine)
    return q.execute()

def importa_giacenza_diretta(codice_magazzino, df_import, origine="CONTO DEPOSITO", batch_size=500):
    rows = []
    for _, r in df_import.iterrows():
        codice = clean(r.get("codice", ""))
        lotto = clean(r.get("lotto", ""))
        qta = money(r.get("quantita")) or 0
        if not codice or not lotto or qta <= 0:
            continue
        rows.append({
            "codice_magazzino": codice_magazzino,
            "codice": codice,
            "descrizione": str(r.get("descrizione", "") or ""),
            "lotto": lotto,
            "scadenza": str(r.get("scadenza", "") or "") or None,
            "quantita": qta,
            "origine": origine,
            "stato_record": "Attivo",
        })
    return batch_insert("giacenze", rows, size=batch_size)

def norm(d): d=d.copy(); d.columns=[str(c).strip() for c in d.columns]; return d
def money(v):
    if pd.isna(v): return None
    if isinstance(v,(int,float)): return float(v)
    s=str(v).replace('€','').replace(' ','').strip()
    if ',' in s and '.' in s: s=s.replace('.','').replace(',','.')
    elif ',' in s: s=s.replace(',','.')
    try: return float(s)
    except: return None
def clean(v):
    if pd.isna(v): return ''
    if isinstance(v,float) and v.is_integer(): return str(int(v))
    return str(v).strip()
def idx(cols, keys, default=0):
    for k in keys:
        if k in cols: return cols.index(k)
    for i,c in enumerate(cols):
        if any(str(k).lower() in str(c).lower() for k in keys): return i
    return default
def idxo(cols, keys):
    opts=['']+cols
    for k in keys:
        if k in cols: return opts.index(k)
    for c in cols:
        if any(str(k).lower() in str(c).lower() for k in keys): return opts.index(c)
    return 0
def ncode(c): return re.sub(r'[^A-Z0-9]','',str(c or '').upper().strip())
def save_file(upload):
    Path('uploads').mkdir(exist_ok=True); p=Path('uploads')/f"{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}_{upload.name.replace('/','_')}"; p.write_bytes(upload.getbuffer()); return str(p)
def validate_prod(t):
    u=str(t or '').upper()
    return 'Validato J&J' if any(x in u for x in ['J&J','JOHNSON','DEPUY','SYNTHES','DE PUY']) else ('Marchio non letto' if not u else 'Prodotto non J&J')
def excel_bytes(sheets):
    import io
    bio=io.BytesIO()
    with pd.ExcelWriter(bio, engine='xlsxwriter') as w:
        for n,d in sheets.items(): d.to_excel(w,index=False,sheet_name=n[:31])
    return bio.getvalue()

def mags():
    # Lettura tollerante: non ordinare su una colonna che potrebbe non esistere.
    d=df('magazzini','id')
    if d.empty:
        try:
            upsert(
                'magazzini',
                {'codice_magazzino':'MAG1','nome_magazzino':'Magazzino 1','tipo':'INTERNO'},
                'codice_magazzino'
            )
            st.cache_data.clear()
            d=df('magazzini','id')
        except Exception:
            pass
    return d

def magazzini_labels():
    d = mags()
    labels = []
    if not d.empty:
        for _, r in d.iterrows():
            codice = clean(
                r.get('codice_magazzino',
                r.get('codice',
                r.get('magazzino', '')))
            )
            nome = str(
                r.get('nome_magazzino',
                r.get('descrizione',
                r.get('nome', '')))
                or ''
            ).strip()
            if codice:
                labels.append(f"{codice} - {nome or codice}")
    # L'app resta utilizzabile anche se l'anagrafica è incompleta.
    return labels or ['MAG1 - Magazzino 1']
def clienti_opts():
    d=df('clienti','descrizione')
    return [{'label':str(r.descrizione),'codice_cliente':str(r.codice_cliente),'descrizione':str(r.descrizione)} for r in d.itertuples()] if not d.empty else []
@st.cache_data(ttl=60)
def price_map(codice_cliente, linea):
    links = sb().table('offerte_clienti').select('offerta_id').eq('codice_cliente', codice_cliente).execute().data or []
    ids = [int(x['offerta_id']) for x in links if x.get('offerta_id') is not None]
    if not ids:
        return {}

    heads = []
    for oid in ids:
        h = sb().table('offerte_header').select('id,linea').eq('id', oid).execute().data or []
        if h and str(h[0].get('linea','')).upper() == str(linea).upper():
            heads.append(oid)

    out = {}
    for oid in heads:
        start = 0
        step = 1000
        while True:
            rows = sb().table('offerte_prezzi').select('codice,prezzo').eq('offerta_id', oid).range(start, start + step - 1).execute().data or []
            for p in rows:
                out[ncode(p.get('codice'))] = float(p.get('prezzo') or 0)
            if len(rows) < step:
                break
            start += step
    return out

def prezzo_per(codice_cliente,codice,linea):
    return price_map(codice_cliente, linea).get(ncode(codice))
def movimento(tipo, mag, codice, lotto, qta, descr='', scad=None, origine='CONTO DEPOSITO', ref_tipo='', ref_id='', note=''):
    return ins('movimenti_magazzino', movimento_row(tipo, mag, codice, lotto, qta, descr, scad, origine, ref_tipo, ref_id, note))

def movimento_row(tipo, mag, codice, lotto, qta, descr='', scad=None, origine='CONTO DEPOSITO', ref_tipo='', ref_id='', note=''):
    return {
        'tipo_movimento':tipo,
        'codice_magazzino':mag,
        'codice':codice,
        'descrizione':descr,
        'lotto':lotto,
        'scadenza':scad or None,
        'quantita':float(qta),
        'origine':origine,
        'riferimento_tipo':ref_tipo,
        'riferimento_id':str(ref_id or ''),
        'note':note,
        'utente':st.session_state.get('user','')
    }

@st.cache_data(show_spinner=False)
def read_excel_cached(file_bytes, file_name):
    import io
    return norm(pd.read_excel(io.BytesIO(file_bytes)))
def disp(mag,codice,lotto):
    rows=sb().table('giacenze').select('*').eq('codice_magazzino',mag).eq('lotto',lotto).execute().data or []
    return sum(float(r.get('quantita') or 0) for r in rows if ncode(r.get('codice'))==ncode(codice))


def revenue_dataset():
    """Unisce righe intervento e interventi per costruire KPI temporali e per agente/cliente."""
    righe = df('righe_intervento','id',True)
    interventi = df('interventi','id',True)
    if righe.empty:
        return pd.DataFrame()
    out = righe.copy()
    if 'totale' not in out.columns:
        out['totale'] = 0.0
    out['totale'] = pd.to_numeric(out['totale'], errors='coerce').fillna(0.0)
    if 'quantita' in out.columns:
        out['quantita'] = pd.to_numeric(out['quantita'], errors='coerce').fillna(0.0)
    if not interventi.empty and 'intervento_id' in out.columns and 'id' in interventi.columns:
        cols = [c for c in ['id','data_intervento','cliente','codice_cliente','agente','linea','magazzino_scarico'] if c in interventi.columns]
        meta = interventi[cols].copy().rename(columns={'id':'intervento_id'})
        out['intervento_id'] = out['intervento_id'].astype(str)
        meta['intervento_id'] = meta['intervento_id'].astype(str)
        # Evita colonne duplicate già presenti nelle righe.
        duplicate_meta = [c for c in meta.columns if c != 'intervento_id' and c in out.columns]
        meta = meta.drop(columns=duplicate_meta, errors='ignore')
        out = out.merge(meta, on='intervento_id', how='left')
    if 'data_intervento' in out.columns:
        out['data_intervento'] = pd.to_datetime(out['data_intervento'], errors='coerce')
    else:
        out['data_intervento'] = pd.NaT
    # Sicurezza supplementare per gli agenti: filtra anche le righe unite agli interventi.
    if current_role() == 'Agente' and 'agente' in out.columns:
        out = out[out['agente'].astype(str).str.casefold() == current_agent().casefold()]
    return out

def euro(value):
    try:
        return f"€ {float(value):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    except Exception:
        return '€ 0,00'

def render_revenue_charts(data, key_prefix='rev'):
    if data.empty or data['data_intervento'].isna().all():
        st.info('Servono interventi con data e righe valorizzate per visualizzare i grafici.')
        return
    valid = data.dropna(subset=['data_intervento']).copy()
    valid['mese'] = valid['data_intervento'].dt.to_period('M').dt.to_timestamp()
    mensile = valid.groupby('mese', as_index=False)['totale'].sum().sort_values('mese')
    mensile['Media mobile 3 mesi'] = mensile['totale'].rolling(3, min_periods=1).mean()

    st.subheader('Andamento del fatturato')
    st.caption('Passa il mouse sui grafici per consultare valori e periodi; usa il menu del grafico per espandere o scaricare.')
    st.line_chart(
        mensile.set_index('mese')[['totale','Media mobile 3 mesi']],
        use_container_width=True,
        height=360
    )

    c1, c2 = st.columns(2)
    with c1:
        st.subheader('Fatturato per cliente')
        if 'cliente' in valid.columns:
            top_clienti = (valid.assign(cliente=valid['cliente'].fillna('Non assegnato').replace('', 'Non assegnato'))
                           .groupby('cliente', as_index=False)['totale'].sum()
                           .sort_values('totale', ascending=False).head(10))
            st.bar_chart(top_clienti.set_index('cliente')['totale'], use_container_width=True, height=340)
        else:
            st.info('Campo cliente non disponibile.')
    with c2:
        st.subheader('Fatturato per agente')
        if 'agente' in valid.columns:
            top_agenti = (valid.assign(agente=valid['agente'].fillna('Non assegnato').replace('', 'Non assegnato'))
                          .groupby('agente', as_index=False)['totale'].sum()
                          .sort_values('totale', ascending=False).head(10))
            st.bar_chart(top_agenti.set_index('agente')['totale'], use_container_width=True, height=340)
        else:
            st.info('Campo agente non disponibile.')

# Login
if 'user' not in st.session_state:
    st.sidebar.title('OrthoFlow 7.1')
    st.sidebar.caption('Accesso protetto')
    with st.sidebar.form('login'):
        u=st.text_input('Utente')
        p=st.text_input('Password',type='password')
        ok=st.form_submit_button('Accedi', use_container_width=True)
    if ok:
        auth = login_user(u, p)
        if auth:
            st.session_state.user = auth.get("username", u)
            st.session_state.ruolo = auth.get("ruolo", "Agente")
            st.session_state.agente_nome = auth.get("agente_nome", "") or ""
            st.session_state.utente_id = auth.get("id")
            try:
                sb().table("utenti_app").update({"ultimo_accesso":"now()"}).eq("id", auth.get("id")).execute()
            except Exception:
                pass
            audit_log("LOGIN", "utenti_app", auth.get("id",""), "Accesso eseguito")
            st.rerun()
        # Accesso di emergenza mantenuto per non bloccare l'amministratore
        elif (u,p)==('admin','Mastrota09@'):
            st.session_state.user=u
            st.session_state.ruolo='Admin'
            st.session_state.agente_nome=''
            st.session_state.utente_id=''
            audit_log("LOGIN_EMERGENZA", "utenti_app", "", "Accesso admin fallback")
            st.rerun()
        else:
            st.sidebar.error('Credenziali errate o utente disattivato')
    st.title('OrthoFlow 7.2 Enterprise')
    st.info('Inserisci le credenziali fornite dall’amministratore.')
    st.stop()

st.sidebar.markdown('## 🏥 OrthoFlow 7.2')
st.sidebar.caption('Gestionale ortopedico cloud')
label_accesso = f"{st.session_state.user} - {st.session_state.ruolo}"
if current_agent():
    label_accesso += f" - {current_agent()}"
st.sidebar.success(label_accesso)

if st.sidebar.button('Esci', use_container_width=True):
    audit_log("LOGOUT", "utenti_app", st.session_state.get("utente_id",""), "Uscita")
    st.session_state.clear()
    st.rerun()

admin = is_admin()
menu_admin=['Dashboard','Gestione dati','Agenti','Cartella clinica','Clienti','Magazzini','Inventario','Offerte','DDT carico / Loan','Scarico sala','Archivio impianti','Work Implant','Customer Connect','KPI e Fatturato','Anomalie','Audit Log']
menu_magazzino=['Dashboard','Inventario','DDT carico / Loan','Scarico sala','Archivio impianti','Customer Connect','Anomalie']
menu_amministrazione=['Dashboard','Cartella clinica','Clienti','Offerte','Archivio impianti','Work Implant','Customer Connect','KPI e Fatturato','Anomalie']
menu_agente=['Dashboard','Cartella clinica','Scarico sala','Archivio impianti','Customer Connect','Anomalie']
ruolo = current_role()
if ruolo == 'Admin':
    menu_items = menu_admin
elif ruolo == 'Magazzino':
    menu_items = menu_magazzino
elif ruolo == 'Amministrazione':
    menu_items = menu_amministrazione
else:
    menu_items = menu_agente
menu=st.sidebar.radio('Menu', menu_items)
if 'quick_menu' in st.session_state:
    qm = st.session_state.pop('quick_menu')
    if qm in menu_items:
        menu=qm

if menu=='Dashboard':
    nome_area = current_agent() if current_role() == 'Agente' else st.session_state.get('user','')
    st.markdown(
        f"""<div class="of-hero"><h2>OrthoFlow 7.2 Enterprise</h2>
        <div class="of-muted">Benvenuto, {nome_area}. Panoramica operativa aggiornata del sistema.</div></div>""",
        unsafe_allow_html=True
    )

    top_a, top_b = st.columns([4,1])
    with top_a:
        st.caption(f"Profilo attivo: {current_role()}" + (f" · Agente: {current_agent()}" if current_agent() else ""))
    with top_b:
        if st.button('🔄 Aggiorna', use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    revenue = revenue_dataset()
    clienti_df=df('clienti')
    giacenze_df=df('giacenze')
    interventi_df=df('interventi')
    movimenti_df=df('movimenti_magazzino')
    anomalie_df=df('anomalie')
    fatt=float(revenue['totale'].sum()) if not revenue.empty else 0.0
    valore_medio=float(revenue.groupby('intervento_id')['totale'].sum().mean()) if not revenue.empty and 'intervento_id' in revenue.columns else 0.0
    anomalie_aperte = len(anomalie_df[anomalie_df['stato'].astype(str).str.casefold()!='risolta']) if not anomalie_df.empty and 'stato' in anomalie_df.columns else len(anomalie_df)

    c1,c2,c3,c4,c5,c6=st.columns(6)
    c1.metric('Fatturato', euro(fatt))
    c2.metric('Interventi',len(interventi_df))
    c3.metric('Valore medio',euro(valore_medio))
    c4.metric('Giacenze',len(giacenze_df))
    c5.metric('Clienti',len(clienti_df))
    c6.metric('Anomalie aperte',anomalie_aperte)

    if not revenue.empty and not revenue['data_intervento'].isna().all():
        today = pd.Timestamp.today().normalize()
        mese_corrente = revenue[revenue['data_intervento'].dt.to_period('M') == today.to_period('M')]['totale'].sum()
        mese_prec = (today - pd.offsets.MonthBegin(1)).to_period('M')
        valore_prec = revenue[revenue['data_intervento'].dt.to_period('M') == mese_prec]['totale'].sum()
        delta = ((mese_corrente-valore_prec)/valore_prec*100) if valore_prec else None
        st.metric('Fatturato mese corrente', euro(mese_corrente), None if delta is None else f'{delta:+.1f}% sul mese precedente')

    st.divider()
    st.subheader('⚡ Azioni rapide')
    allowed = set(menu_items)
    action_defs = [
        ('📸 Scarico sala','Scarico sala'),
        ('📦 Inventario','Inventario'),
        ('💰 Offerte','Offerte'),
        ('🗂️ Archivio','Archivio impianti'),
        ('📊 KPI','KPI e Fatturato'),
        ('🗄️ Gestione dati','Gestione dati'),
    ]
    visible_actions = [x for x in action_defs if x[1] in allowed]
    action_cols = st.columns(min(len(visible_actions), 6)) if visible_actions else []
    for col, (label, target) in zip(action_cols, visible_actions):
        if col.button(label, use_container_width=True):
            st.session_state.quick_menu=target
            st.rerun()

    st.divider()
    render_revenue_charts(revenue, 'dash')

    st.divider()
    a1,a2=st.columns(2)
    with a1:
        st.subheader('⚠️ Anomalie recenti')
        if not anomalie_df.empty:
            st.dataframe(anomalie_df.head(10),use_container_width=True,height=300,hide_index=True)
        else:
            st.success('Nessuna anomalia presente')
    with a2:
        st.subheader('📦 Movimenti recenti')
        if not movimenti_df.empty:
            st.dataframe(movimenti_df.head(10),use_container_width=True,height=300,hide_index=True)
        else:
            st.info('Nessun movimento presente')

elif menu=='Gestione dati':
    st.title('🗄️ Gestione dati')
    st.caption('Modifica, elimina e scarica le principali tabelle operative.')

    if st.button('🔄 Aggiorna tabelle', use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    tab=st.selectbox(
        'Tabella da gestire',
        ['clienti','magazzini','agenti','cartelle_cliniche','giacenze','movimenti_magazzino','interventi','righe_intervento','documenti_impianto','offerte_header','offerte_clienti','offerte_prezzi','ddt','ddt_righe','ordini','ordini_righe','chiusure','chiusure_righe','utenti_app','audit_log','anomalie']
    )
    order_col=st.text_input('Ordina per colonna','id')
    desc=st.checkbox('Ordine decrescente',True)
    data=df(tab,order_col,desc)

    st.write(f'Righe visualizzate: {len(data)}')
    st.dataframe(data,use_container_width=True,height=420)

    if tab == 'documenti_impianto' and not data.empty and 'id' in data.columns:
        st.subheader('📎 Anteprima archivio impianti')
        doc_ids = data['id'].dropna().tolist()
        doc_id = st.selectbox('Seleziona documento da aprire', doc_ids, key='gestione_documento_preview')
        doc_row = data[data['id'] == doc_id].iloc[0].to_dict()
        st.write(f"**Intervento:** {doc_row.get('intervento_id','')}")
        st.write(f"**Cartella clinica:** {doc_row.get('cartella_clinica','')}")
        st.write(f"**Cliente/struttura:** {doc_row.get('cliente','')}")
        st.write(f"**Agente:** {doc_row.get('agente','')}")
        st.write(f"**Nome file:** {doc_row.get('nome_file','')}")
        storage_path = doc_row.get('storage_path','')
        signed = storage_signed_url(storage_path) if storage_path else None
        if signed:
            st.link_button('📂 Apri documento originale', signed, use_container_width=True)
        else:
            st.warning('File non disponibile su Supabase Storage oppure percorso non registrato.')

    if not data.empty:
        st.download_button('⬇️ Scarica Excel', excel_bytes({tab:data}), file_name=f'{tab}.xlsx', use_container_width=True)

    st.divider()
    st.subheader('✏️ Modifica / 🗑️ Elimina record')

    if data.empty:
        st.info('Nessun dato presente in questa tabella.')
    elif 'id' not in data.columns:
        st.warning('Questa tabella non ha una colonna ID: modifica/elimina non disponibili.')
    else:
        ids=data['id'].dropna().tolist()
        selected_id=st.selectbox('Seleziona ID record', ids)
        row=data[data['id']==selected_id].iloc[0].to_dict()

        cmod, cdel = st.tabs(['✏️ Modifica record','🗑️ Elimina record'])

        with cmod:
            st.caption('Modifica i campi e salva. Evita di cambiare campi tecnici se non sei sicuro.')
            edit={}
            for col,val in row.items():
                if col=='id':
                    st.text_input(col, str(val), disabled=True, key=f'{tab}_{selected_id}_{col}')
                else:
                    edit[col]=st.text_input(col, '' if pd.isna(val) else str(val), key=f'{tab}_{selected_id}_{col}')
            if st.button('💾 Salva modifiche', use_container_width=True):
                payload={}
                for col,val in edit.items():
                    old=row.get(col)
                    payload[col]=cast_like(val, old)
                try:
                    upd(tab, selected_id, payload)
                    st.cache_data.clear()
                    st.success('Record modificato correttamente.')
                    st.rerun()
                except Exception as e:
                    st.error(f'Errore modifica: {e}')

        with cdel:
            st.error('Attenzione: eliminazione definitiva dal database.')
            conferma=st.checkbox(f'Confermo eliminazione ID {selected_id} dalla tabella {tab}')
            if st.button('🗑️ Elimina definitivamente', use_container_width=True, disabled=not conferma):
                try:
                    if tab == 'documenti_impianto':
                        storage_delete_file(row.get('storage_path',''), row.get('storage_bucket','orthoflow-impianti') or 'orthoflow-impianti')
                    dele(tab, selected_id)
                    st.cache_data.clear()
                    st.success('Record eliminato definitivamente.')
                    st.rerun()
                except Exception as e:
                    st.error(f'Errore eliminazione: {e}')


    st.divider()
    st.subheader("🛠️ Amministrazione Database")
    st.warning("Prima di cancellare, scarica il backup Excel della tabella.")

    cma, cmb = st.columns(2)
    with cma:
        conf_mass = st.text_input(f"Per svuotare la tabella scrivi SVUOTA {tab}", key=f"mass_empty_{tab}")
        if st.button(f"🗑️ Svuota tutta la tabella {tab}", use_container_width=True, key=f"btn_mass_empty_{tab}"):
            if conf_mass != f"SVUOTA {tab}":
                st.error(f"Conferma non valida. Scrivi esattamente: SVUOTA {tab}")
            else:
                n_del = svuota_tabella(tab)
                st.cache_data.clear()
                st.success(f"Tabella {tab} svuotata. Righe eliminate: {n_del}")
                st.rerun()

    with cmb:
        st.caption("Reset operativo: non cancella clienti, offerte e magazzini.")
        conf_reset = st.text_input("Per reset operativo scrivi RESET OPERATIVO", key="reset_operativo_confirm")
        if st.button("⚠️ Reset operativo", use_container_width=True):
            if conf_reset != "RESET OPERATIVO":
                st.error("Conferma non valida. Scrivi esattamente: RESET OPERATIVO")
            else:
                total = 0
                for rt in ["giacenze","movimenti_magazzino","interventi","righe_intervento","ddt","ddt_righe","anomalie","documenti_impianto"]:
                    try:
                        total += svuota_tabella(rt)
                    except Exception as sub_e:
                        st.warning(f"Tabella {rt} non svuotata: {sub_e}")
                st.cache_data.clear()
                st.success(f"Reset operativo completato. Righe eliminate totali: {total}")
                st.rerun()


elif menu=='Agenti':
    st.title('👤 Agenti e accessi')
    st.caption('Crea l’agente e assegna username, password e permessi. Le password sono salvate come hash, mai in chiaro.')

    t_ag, t_user = st.tabs(['Anagrafica agenti','Accessi e password'])

    with t_ag:
        a=df('agenti','nome')
        with st.form('nuovo_agente'):
            nome=st.text_input('Nome agente')
            email=st.text_input('Email')
            telefono=st.text_input('Telefono')
            attivo=st.checkbox('Attivo', True)
            ok_ag=st.form_submit_button('Salva agente')
        if ok_ag:
            if not nome.strip():
                st.warning('Inserisci il nome agente.')
            else:
                try:
                    ins('agenti',{'nome':nome.strip(),'email':email.strip(),'telefono':telefono.strip(),'attivo':attivo})
                    st.cache_data.clear()
                    st.success('Agente salvato.')
                    st.rerun()
                except Exception as e:
                    st.error(f'Errore salvataggio agente: {e}')
        st.dataframe(df('agenti','nome'),use_container_width=True,height=360)

    with t_user:
        agenti_df=df('agenti','nome')
        agenti_nomi=agenti_df['nome'].dropna().astype(str).tolist() if not agenti_df.empty and 'nome' in agenti_df.columns else []
        with st.form('nuovo_accesso'):
            username=st.text_input('Username')
            password=st.text_input('Password assegnata da te',type='password')
            password2=st.text_input('Ripeti password',type='password')
            ruolo_utente=st.selectbox('Ruolo',['Agente','Magazzino','Amministrazione','Admin'])
            agente_nome=st.selectbox('Agente collegato',['']+agenti_nomi, disabled=ruolo_utente!='Agente')
            attivo_user=st.checkbox('Accesso attivo',True)
            salva_user=st.form_submit_button('Crea accesso',use_container_width=True)
        if salva_user:
            if not username.strip() or len(password)<8:
                st.error('Inserisci username e una password di almeno 8 caratteri.')
            elif password != password2:
                st.error('Le due password non coincidono.')
            elif ruolo_utente=='Agente' and not agente_nome:
                st.error('Collega l’accesso a un agente.')
            else:
                try:
                    salt, phash=password_hash(password)
                    sb().table('utenti_app').insert({
                        'username':username.strip(),
                        'password_salt':salt,
                        'password_hash':phash,
                        'ruolo':ruolo_utente,
                        'agente_nome':agente_nome if ruolo_utente=='Agente' else '',
                        'attivo':attivo_user
                    }).execute()
                    audit_log('CREAZIONE_ACCESSO','utenti_app',username.strip(),ruolo_utente)
                    st.cache_data.clear()
                    st.success('Accesso creato. Comunica username e password all’utente.')
                    st.rerun()
                except Exception as e:
                    st.error(f'Impossibile creare accesso: {e}')

        users=df('utenti_app','username')
        if users.empty:
            st.info('Nessun accesso registrato nella tabella utenti_app.')
        else:
            cols_show=[c for c in ['id','username','ruolo','agente_nome','attivo','ultimo_accesso','created_at'] if c in users.columns]
            st.dataframe(users[cols_show],use_container_width=True,height=320)
            ids=users['id'].dropna().tolist()
            uid=st.selectbox('Utente da gestire',ids)
            urow=users[users['id']==uid].iloc[0].to_dict()
            c1,c2=st.columns(2)
            with c1:
                nuovo_stato=st.checkbox('Utente attivo',bool(urow.get('attivo',True)),key=f'attivo_{uid}')
                if st.button('Salva stato accesso',use_container_width=True):
                    upd('utenti_app',uid,{'attivo':nuovo_stato})
                    st.cache_data.clear()
                    st.success('Stato aggiornato.')
                    st.rerun()
            with c2:
                nuova_password=st.text_input('Nuova password',type='password',key=f'pwd_{uid}')
                if st.button('Reimposta password',use_container_width=True):
                    if len(nuova_password)<8:
                        st.error('Password di almeno 8 caratteri.')
                    else:
                        salt,phash=password_hash(nuova_password)
                        upd('utenti_app',uid,{'password_salt':salt,'password_hash':phash})
                        st.success('Password reimpostata.')

elif menu=='Cartella clinica':
    st.title('📁 Cartella clinica')
    st.caption('Gestione cartelle cliniche collegate agli interventi.')

    t1,t2=st.tabs(['Nuova cartella','Cartelle presenti'])

    with t1:
        clienti=clienti_opts()
        interventi=df('interventi','id',True)
        with st.form('cartella_clinica'):
            if clienti:
                cs=st.selectbox('Struttura / cliente',clienti,format_func=lambda x:x['label'])
                codice_cliente=cs['codice_cliente']
                cliente=cs['descrizione']
            else:
                codice_cliente=st.text_input('Codice cliente')
                cliente=st.text_input('Cliente / struttura')

            if not interventi.empty and 'id' in interventi.columns:
                intervento_id=st.selectbox('Intervento collegato',['']+[str(x) for x in interventi['id'].dropna().tolist()])
            else:
                intervento_id=st.text_input('Intervento collegato')

            paziente=st.text_input('Paziente / riferimento interno')
            numero_cartella=st.text_input('Numero cartella clinica')
            data_cartella=st.date_input('Data cartella',date.today())
            reparto=st.text_input('Reparto')
            chirurgo=st.text_input('Chirurgo')
            note=st.text_area('Note')
            ok_cart=st.form_submit_button('Salva cartella clinica')

        if ok_cart:
            payload={
                'codice_cliente':codice_cliente,
                'cliente':cliente,
                'intervento_id':None if not intervento_id else str(intervento_id),
                'paziente':paziente,
                'numero_cartella':numero_cartella,
                'data_cartella':str(data_cartella),
                'reparto':reparto,
                'chirurgo':chirurgo,
                'note':note
            }
            try:
                ins('cartelle_cliniche',payload)
                st.cache_data.clear()
                st.success('Cartella clinica salvata.')
                st.rerun()
            except Exception as e:
                st.error(f'Errore salvataggio cartella clinica. Probabilmente manca la tabella cartelle_cliniche in Supabase. Dettaglio: {e}')

    with t2:
        dcart=df('cartelle_cliniche','id',True)
        st.dataframe(dcart,use_container_width=True,height=520)
        if not dcart.empty:
            st.download_button('⬇️ Scarica cartelle cliniche Excel', excel_bytes({'cartelle_cliniche':dcart}), file_name='cartelle_cliniche.xlsx', use_container_width=True)

elif menu=='Clienti':
    st.title('👥 Clienti')
    t1,t2=st.tabs(['Import ANAGRA','Clienti presenti'])
    with t1:
        f=st.file_uploader('ANAGRA Excel',type=['xlsx','xls'])
        if f:
            d=read_excel_cached(f.getvalue(), f.name); st.dataframe(d.head(30),use_container_width=True); cols=list(d.columns)
            cc=st.selectbox('Codice cliente',cols,index=idx(cols,['Codice','codice_cliente'])); de=st.selectbox('Descrizione',cols,index=idx(cols,['Descrizione','Cliente'],1 if len(cols)>1 else 0)); ci=st.selectbox('Città',['']+cols,index=idxo(cols,['Città','Citta'])); pr=st.selectbox('Provincia',['']+cols,index=idxo(cols,['Prov','Provincia'])); pv=st.selectbox('P.IVA',['']+cols,index=idxo(cols,['Partita Iva','PIVA','P.IVA']))
            if st.button('Importa clienti',use_container_width=True):
                rows=[]
                for _,x in d.iterrows():
                    cod=clean(x[cc])
                    if cod:
                        descr = '' if pd.isna(x[de]) else str(x[de])
                        rows.append({
                            'codice_cliente': cod,
                            'descrizione': descr,
                            'descrizione_cliente': descr,
                            'citta': '' if not ci else str(x[ci]),
                            'provincia': '' if not pr else str(x[pr]),
                            'piva': '' if not pv else str(x[pv])
                        })
                n = batch_upsert('clienti', rows, 'codice_cliente', size=500)
                st.success(f'Clienti importati/aggiornati: {n}')
    with t2: st.dataframe(df('clienti','descrizione'),use_container_width=True)
elif menu=='Magazzini':
    st.title('🏬 Magazzini')
    with st.form('mag'):
        cm=st.text_input('Codice magazzino','MAG1'); nm=st.text_input('Nome','Magazzino 1'); tipo=st.selectbox('Tipo',['INTERNO','STRUTTURA','LOAN']); cc=st.text_input('Codice cliente collegato',''); ok=st.form_submit_button('Salva')
    if ok: upsert('magazzini',{'codice_magazzino':cm,'nome_magazzino':nm,'tipo':tipo,'codice_cliente':cc},'codice_magazzino'); st.success('Salvato')
    st.dataframe(mags(),use_container_width=True)
elif menu=='Inventario':
    st.title('📦 Inventario')
    t1,t2,t3=st.tabs(['Import TTKEYS','Giacenze','Movimenti'])
    with t1:
        m=mags(); labels=magazzini_labels(); ml=st.selectbox('Magazzino',labels); mag=ml.split(' - ')[0]; origine=st.selectbox('Origine',['CONTO DEPOSITO','LOAN / CONTO VISIONE'])
        f=st.file_uploader('TTKEYS / giacenze',type=['xlsx','xls'])
        if f:
            d=read_excel_cached(f.getvalue(), f.name); st.dataframe(d.head(30),use_container_width=True); cols=list(d.columns)
            cod=st.selectbox('Codice',cols,index=idx(cols,['Articolo','Codice'])); des=st.selectbox('Descrizione',['']+cols,index=idxo(cols,['Descr. articolo','Descrizione','Descr.'])); lot=st.selectbox('Lotto',cols,index=idx(cols,['Lotto','LOT'])); qty=st.selectbox('Quantità',cols,index=idx(cols,['Quantità','Quantita','Qta'])); sca=st.selectbox('Scadenza',['']+cols,index=idxo(cols,['Scadenza','EXP'])); only=st.checkbox('Solo quantità positive',True)
            if st.button('Importa giacenze',use_container_width=True):
                rows=[]
                prog = st.progress(0)
                total = len(d)
                for i,(_,x) in enumerate(d.iterrows(), start=1):
                    c=clean(x[cod]); l=clean(x[lot]); q=money(x[qty]) or 0
                    if c and l and not (only and q<=0):
                        rows.append(movimento_row('CARICO_INIZIALE',mag,c,l,q,'' if not des else str(x[des]),None if not sca else str(x[sca]),origine,'IMPORT','TTKEYS'))
                    if i % 500 == 0 or i == total:
                        prog.progress(min(i/total, 1.0))
                n=batch_insert('movimenti_magazzino', rows, size=1000)
                st.cache_data.clear()
                st.success(f'Movimenti caricati in blocco: {n}')
    with t2: st.dataframe(df('giacenze','updated_at',True),use_container_width=True)
    with t3: st.dataframe(df('movimenti_magazzino','id',True),use_container_width=True)
elif menu=='Offerte':
    st.title('💰 Offerte')
    st.info('Import ottimizzato: i prezzi vengono caricati in blocchi da 500 righe. Il matching resta J&J Safe Match: 413.050S ≠ 413.050.')
    t1,t2,t3=st.tabs(['Crea','Import prezzi','Visualizza/Test'])
    with t1:
        with st.form('off'):
            nome=st.text_input('Nome offerta','Federico II Trauma'); linea=st.selectbox('Linea',['TRAUMA','PROTESICA','CMF','SPINE','SPORTS','ALTRO']); clienti=st.text_area('Codici clienti','9010062'); ok=st.form_submit_button('Crea offerta')
        if ok:
            h=ins('offerte_header',{'nome_offerta':nome,'linea':linea})
            for x in clienti.replace(',', '\n').splitlines():
                x=x.strip()
                if x: ins('offerte_clienti',{'offerta_id':h['id'],'codice_cliente':x})
            st.success(f"Offerta ID {h['id']}")
    with t2:
        o=df('offerte_header','id',True)
        if not o.empty:
            sel=st.selectbox('Offerta',[f'{r.id} - {r.nome_offerta} ({r.linea})' for r in o.itertuples()]); oid=int(sel.split(' - ')[0]); f=st.file_uploader('Excel prezzi',type=['xlsx','xls'])
            if f:
                d=read_excel_cached(f.getvalue(), f.name); st.dataframe(d.head(30),use_container_width=True); cols=list(d.columns); cod=st.selectbox('Codice',cols,index=idx(cols,['Codice Prodotto','Codice','Articolo'])); des=st.selectbox('Descrizione',['']+cols,index=idxo(cols,['Descrizione prodotto','Descrizione'])); pre=st.selectbox('Prezzo',cols,index=idx(cols,['Prezzo unitario offerto cifre e lettere','Prezzo','prezzo']))
                if st.button('Importa prezzi',use_container_width=True):
                    rows=[]
                    for _,x in d.iterrows():
                        c=clean(x[cod]); p=money(x[pre])
                        if c and p is not None:
                            rows.append({
                                'offerta_id': oid,
                                'codice': c,
                                'descrizione': '' if not des else str(x[des]),
                                'prezzo': p
                            })
                    n = batch_insert('offerte_prezzi', rows, size=500)
                    price_map.clear()
                    st.success(f'Prezzi importati: {n}')
    with t3:
        st.dataframe(df('offerte_header','id',True),use_container_width=True); st.dataframe(df('offerte_clienti','id',True),use_container_width=True); st.dataframe(df('offerte_prezzi','id',True),use_container_width=True)
elif menu=='DDT carico / Loan':
    st.title('🚚 DDT carico / Loan')
    t1,t2=st.tabs(['Import Excel','Storico'])
    with t1:
        labels=magazzini_labels(); ml=st.selectbox('Magazzino destinazione',labels); mag=ml.split(' - ')[0]; tipo=st.selectbox('Tipo',['CONTO DEPOSITO','LOAN / CONTO VISIONE'])
        f=st.file_uploader('Excel DDT',type=['xlsx','xls'])
        if f:
            d=read_excel_cached(f.getvalue(), f.name); st.dataframe(d.head(30),use_container_width=True); cols=list(d.columns); cod=st.selectbox('Codice',cols,index=idx(cols,['Codice','Articolo','REF'])); lot=st.selectbox('Lotto',cols,index=idx(cols,['Lotto','LOT'])); qty=st.selectbox('Quantità',cols,index=idx(cols,['Quantità','Qta','Qty'])); des=st.selectbox('Descrizione',['']+cols,index=idxo(cols,['Descrizione','Descr.'])); sca=st.selectbox('Scadenza',['']+cols,index=idxo(cols,['Scadenza','EXP']))
            num=st.text_input('Numero DDT',''); cli=st.text_input('Cliente/destinazione','')
            if st.button('Crea DDT e carica magazzino',use_container_width=True):
                ddt=ins('ddt',{'numero_ddt':num,'data_ddt':str(date.today()),'tipo_ddt':tipo,'cliente':cli,'codice_magazzino_destinazione':mag})
                righe=[]; movs=[]
                for _,x in d.iterrows():
                    c=clean(x[cod]); l=clean(x[lot]); q=money(x[qty]) or 1
                    if c and l:
                        descrizione='' if not des else str(x[des])
                        scadenza=None if not sca else str(x[sca])
                        righe.append({'ddt_id':ddt['id'],'codice':c,'descrizione':descrizione,'lotto':l,'scadenza':scadenza,'quantita':q,'origine':tipo})
                        movs.append(movimento_row('CARICO_DDT',mag,c,l,q,descrizione,scadenza,tipo,'DDT',ddt['id']))
                n1=batch_insert('ddt_righe', righe, size=1000)
                n2=batch_insert('movimenti_magazzino', movs, size=1000)
                st.cache_data.clear()
                st.success(f'DDT {ddt["id"]} creato. Righe: {n1}. Movimenti: {n2}')
    with t2: st.dataframe(df('ddt','id',True),use_container_width=True); st.dataframe(df('ddt_righe','id',True),use_container_width=True)
elif menu=='Scarico sala':
    st.title('📸 Scarico sala')
    clienti=clienti_opts(); labels=magazzini_labels()
    rows=[]
    up=st.file_uploader('Foto scarico sala',type=['jpg','jpeg','png'])
    if up:
        path=salva_file_locale(up, "impianti")
        st.session_state["scarico_file_path"]=path
        st.session_state["scarico_file_name"]=up.name
        st.session_state["scarico_file_type"]=up.type or ""
        st.image(up,use_container_width=True)
        if st.button('Estrai OCR AI',use_container_width=True):
            if not ai_enabled(): st.error('OCR AI non configurato o quota API non disponibile')
            else:
                meta=analyze_image(path,mode='scarico_sala'); rows=normalize_ai_items(meta); st.session_state['scarico_rows']=rows; st.success(f'Righe estratte: {len(rows)}')
    edited=st.data_editor(pd.DataFrame(st.session_state.get('scarico_rows',[])) if st.session_state.get('scarico_rows') else pd.DataFrame(columns=['codice','descrizione','lotto','scadenza','quantita','produttore']),num_rows='dynamic',use_container_width=True)
    with st.form('intervento'):
        data_int=st.date_input('Data intervento',date.today()); cs=st.selectbox('Struttura',clienti,format_func=lambda x:x['label']) if clienti else {'codice_cliente':'','descrizione':''}; cartella_clinica=st.text_input('Numero cartella clinica',''); ml=st.selectbox('Scarica da giacenza',labels); mag=ml.split(' - ')[0]; agenti=safe_agenti_opts(); agente=st.selectbox('Agente', agenti) if agenti and agenti!=[''] else st.text_input('Agente',''); linea=st.selectbox('Linea',['TRAUMA','PROTESICA','CMF','SPINE','SPORTS','ALTRO']); ok=st.form_submit_button('Crea intervento e scarica')
    if ok:
        inter=ins('interventi',{'data_intervento':str(data_int),'codice_cliente':cs['codice_cliente'],'cliente':cs['descrizione'],'cartella_clinica':cartella_clinica,'agente':agente,'linea':linea,'magazzino_scarico':mag}); fatt=0; n=0
        if st.session_state.get("scarico_file_path"):
            salva_documento_impianto(inter["id"], st.session_state.get("scarico_file_path"), st.session_state.get("scarico_file_name",""), st.session_state.get("scarico_file_type",""), codice_cliente=cs["codice_cliente"], cliente=cs["descrizione"], agente=agente, data_intervento=data_int, cartella_clinica=cartella_clinica, note="Documento originale caricato da Scarico sala")
        for _,x in edited.iterrows():
            c=clean(x.get('codice','')); l=clean(x.get('lotto','')); q=money(x.get('quantita')) or 1; descr=str(x.get('descrizione','') or ''); prod=str(x.get('produttore','') or '')
            if not c or not l: continue
            valid=validate_prod(prod)
            pr=prezzo_per(cs['codice_cliente'],c,linea)
            tot=pr*q if pr is not None else None
            if pr is None:
                ins_safe('anomalie',{'tipo':'PREZZO_NON_TROVATO','gravita':'Media','descrizione':f'Intervento {inter["id"]}: prezzo non trovato per cliente {cs["codice_cliente"]}, linea {linea}, codice {c}. Verifica offerta e S sterile/non sterile.','stato':'Aperta'})
            ins('righe_intervento',{'intervento_id':inter['id'],'codice':c,'descrizione':descr,'lotto':l,'scadenza':str(x.get('scadenza','') or '') or None,'quantita':q,'produttore':prod,'validazione':valid,'origine':'CONTO DEPOSITO','prezzo':pr,'totale':tot,'reintegro':True})
            if disp(mag,c,l)<q: ins_safe('anomalie',{'tipo':'GIACENZA_INSUFFICIENTE','gravita':'Alta','descrizione':f'Intervento {inter["id"]}: {c} lotto {l} disponibile {disp(mag,c,l)} richiesta {q}','stato':'Aperta'})
            movimento('SCARICO_INTERVENTO',mag,c,l,-abs(q),descr,str(x.get('scadenza','') or '') or None,'CONTO DEPOSITO','INTERVENTO',inter['id']); fatt+=tot or 0; n+=1
        st.success(f'Intervento {inter["id"]} creato. Righe: {n}. Fatturato: € {fatt:,.2f}')


elif menu=='Archivio impianti':
    st.title('🗂️ Archivio impianti')
    st.caption('Consultazione rapida dei documenti originali. Modifica ed eliminazione restano disponibili anche in Gestione dati.')
    docs=df('documenti_impianto','id',True)
    if docs.empty:
        st.info('Nessun documento impianto archiviato.')
    else:
        c1,c2,c3,c4=st.columns(4)
        filtro_cliente=c1.text_input('Cliente / struttura')
        filtro_agente=c2.text_input('Agente', value=current_agent() if current_role()=='Agente' else '')
        filtro_intervento=c3.text_input('ID intervento')
        filtro_cartella=c4.text_input('Cartella clinica')
        view=docs.copy()
        if filtro_cliente and 'cliente' in view.columns:
            view=view[view['cliente'].astype(str).str.contains(filtro_cliente,case=False,na=False)]
        if filtro_agente and 'agente' in view.columns:
            view=view[view['agente'].astype(str).str.contains(filtro_agente,case=False,na=False)]
        if filtro_intervento and 'intervento_id' in view.columns:
            view=view[view['intervento_id'].astype(str).str.contains(filtro_intervento,case=False,na=False)]
        if filtro_cartella and 'cartella_clinica' in view.columns:
            view=view[view['cartella_clinica'].astype(str).str.contains(filtro_cartella,case=False,na=False)]
        st.dataframe(view,use_container_width=True,height=420)
        if not view.empty and 'id' in view.columns:
            st.download_button(
                '⬇️ Esporta elenco Excel',
                excel_bytes({'documenti_impianto':view}),
                file_name='archivio_impianti.xlsx',
                use_container_width=True
            )
            selected=st.selectbox('Documento da aprire', view['id'].dropna().tolist())
            row=view[view['id']==selected].iloc[0].to_dict()
            st.write(f"**Intervento:** {row.get('intervento_id','')}")
            st.write(f"**Cartella clinica:** {row.get('cartella_clinica','')}")
            st.write(f"**Cliente:** {row.get('cliente','')}")
            st.write(f"**Agente:** {row.get('agente','')}")
            st.write(f"**File:** {row.get('nome_file','')}")
            signed=storage_signed_url(row.get('storage_path','')) if row.get('storage_path') else None
            if signed:
                st.link_button('📎 Apri documento originale', signed, use_container_width=True)
            else:
                st.warning('File non disponibile in Supabase Storage.')

elif menu=='Work Implant': st.title('📄 Work Implant'); st.dataframe(df('righe_intervento','id',True),use_container_width=True)
elif menu=='Customer Connect':
    st.title('🔁 Customer Connect'); r=df('righe_intervento')
    if not r.empty: st.dataframe(r.groupby('codice',as_index=False)['quantita'].sum(),use_container_width=True)
elif menu=='KPI e Fatturato':
    st.title('📊 KPI e Fatturato')
    st.caption('Analisi interattiva del fatturato teorico prodotto dagli interventi.')
    revenue = revenue_dataset()
    if revenue.empty:
        st.info('Non sono ancora presenti righe intervento valorizzate.')
    else:
        min_data = revenue['data_intervento'].dropna().min()
        max_data = revenue['data_intervento'].dropna().max()
        f1,f2,f3,f4 = st.columns(4)
        with f1:
            data_da = st.date_input('Dal', value=(min_data.date() if pd.notna(min_data) else date.today()), key='kpi_da')
        with f2:
            data_a = st.date_input('Al', value=(max_data.date() if pd.notna(max_data) else date.today()), key='kpi_a')
        with f3:
            agenti_kpi = ['Tutti'] + sorted(revenue['agente'].dropna().astype(str).unique().tolist()) if 'agente' in revenue.columns else ['Tutti']
            agente_kpi = st.selectbox('Agente', agenti_kpi, key='kpi_agente')
        with f4:
            linee_kpi = ['Tutte'] + sorted(revenue['linea'].dropna().astype(str).unique().tolist()) if 'linea' in revenue.columns else ['Tutte']
            linea_kpi = st.selectbox('Linea', linee_kpi, key='kpi_linea')

        view = revenue.copy()
        if 'data_intervento' in view.columns:
            view = view[(view['data_intervento'].dt.date >= data_da) & (view['data_intervento'].dt.date <= data_a)]
        if agente_kpi != 'Tutti' and 'agente' in view.columns:
            view = view[view['agente'].astype(str) == agente_kpi]
        if linea_kpi != 'Tutte' and 'linea' in view.columns:
            view = view[view['linea'].astype(str) == linea_kpi]

        totale = float(view['totale'].sum()) if not view.empty else 0.0
        interventi_n = view['intervento_id'].nunique() if not view.empty and 'intervento_id' in view.columns else 0
        pezzi = float(view['quantita'].sum()) if not view.empty and 'quantita' in view.columns else 0.0
        media = totale/interventi_n if interventi_n else 0.0
        prodotti = view['codice'].nunique() if not view.empty and 'codice' in view.columns else 0

        k1,k2,k3,k4,k5=st.columns(5)
        k1.metric('Fatturato filtrato',euro(totale))
        k2.metric('Interventi',interventi_n)
        k3.metric('Valore medio/intervento',euro(media))
        k4.metric('Quantità impiantata',f'{pezzi:,.0f}')
        k5.metric('Codici distinti',prodotti)

        st.divider()
        render_revenue_charts(view, 'kpi')

        st.divider()
        c1,c2=st.columns(2)
        with c1:
            st.subheader('Top prodotti per fatturato')
            if not view.empty and 'codice' in view.columns:
                prod = view.groupby('codice',as_index=False).agg(Fatturato=('totale','sum'), Quantità=('quantita','sum') if 'quantita' in view.columns else ('totale','size')).sort_values('Fatturato',ascending=False).head(20)
                st.dataframe(prod,use_container_width=True,hide_index=True,height=420)
        with c2:
            st.subheader('Dettaglio interventi')
            if not view.empty and 'intervento_id' in view.columns:
                agg_map={'totale':'sum'}
                dettaglio=view.groupby('intervento_id',as_index=False).agg(agg_map).sort_values('totale',ascending=False)
                dettaglio=dettaglio.rename(columns={'totale':'Fatturato'})
                st.dataframe(dettaglio,use_container_width=True,hide_index=True,height=420)

        st.download_button(
            '⬇️ Esporta analisi fatturato Excel',
            excel_bytes({'fatturato_filtrato':view}),
            file_name='analisi_fatturato.xlsx',
            use_container_width=True
        )

elif menu=='Audit Log':
    st.title('🧾 Audit Log')
    st.caption('Cronologia di accessi, creazioni, modifiche ed eliminazioni.')
    logs=df('audit_log','id',True)
    if logs.empty:
        st.info('Nessuna attività registrata.')
    else:
        c1,c2,c3=st.columns(3)
        fu=c1.text_input('Filtra utente')
        fa=c2.text_input('Filtra azione')
        ft=c3.text_input('Filtra tabella')
        view=logs.copy()
        if fu and 'utente' in view.columns:
            view=view[view['utente'].astype(str).str.contains(fu,case=False,na=False)]
        if fa and 'azione' in view.columns:
            view=view[view['azione'].astype(str).str.contains(fa,case=False,na=False)]
        if ft and 'tabella' in view.columns:
            view=view[view['tabella'].astype(str).str.contains(ft,case=False,na=False)]
        st.dataframe(view,use_container_width=True,height=520)
        st.download_button('⬇️ Esporta Audit Excel',excel_bytes({'audit_log':view}),file_name='audit_log.xlsx',use_container_width=True)

elif menu=='Anomalie': st.title('⚠️ Anomalie'); st.dataframe(df('anomalie','id',True),use_container_width=True)
