import io
import os
from datetime import date, datetime, time, timedelta

import pandas as pd
import streamlit as st
from supabase import create_client

st.set_page_config(page_title="Customer Connect · OrthoFlow", page_icon="🔁", layout="wide")


def secret(name, default=None):
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.getenv(name, default)


@st.cache_resource
def client():
    url = secret("SUPABASE_URL")
    key = secret("SUPABASE_SERVICE_KEY") or secret("SUPABASE_ANON_KEY") or secret("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("Supabase non configurato nei Secrets")
    return create_client(str(url).rstrip("/"), str(key))


def sb(): return client()
def clean(v):
    if v is None: return ""
    if isinstance(v, float) and pd.isna(v): return ""
    return str(v).strip()
def user(): return clean(st.session_state.get("user"))
def role(): return clean(st.session_state.get("ruolo"))
def agent_name(): return clean(st.session_state.get("agente_nome"))

if not user():
    st.warning("Accedi prima a OrthoFlow Control Tower.")
    st.stop()


@st.cache_data(ttl=60)
def load_data():
    righe = (sb().table("righe_intervento").select("*")
             .order("id", desc=True).limit(10000).execute().data or [])
    interventi = (sb().table("interventi").select("*")
                  .order("id", desc=True).limit(5000).execute().data or [])
    if not righe:
        return pd.DataFrame()
    rdf = pd.DataFrame(righe); idf = pd.DataFrame(interventi)
    if idf.empty or "id" not in idf.columns:
        return pd.DataFrame()
    keep = [c for c in ["id","data_intervento","created_at","codice_cliente","cliente","struttura","cartella_clinica","chirurgo","agente","linea"] if c in idf.columns]
    idf = idf[keep].copy().rename(columns={"id":"intervento_id"})
    out = rdf.merge(idf, on="intervento_id", how="left", suffixes=("","_intervento"))
    if role() == "Agente":
        a = agent_name()
        if a and "agente" in out.columns:
            out = out[out["agente"].astype(str).str.casefold() == a.casefold()]
        elif a:
            out = out.iloc[0:0]
    out["Struttura"] = out.get("cliente", "").fillna("").astype(str) if "cliente" in out.columns else ""
    if "struttura" in out.columns:
        mask = out["Struttura"].astype(str).str.strip().eq("")
        out.loc[mask,"Struttura"] = out.loc[mask,"struttura"].fillna("").astype(str)
    out["Cartella clinica"] = out.get("cartella_clinica", "")
    created = pd.to_datetime(out.get("created_at"), errors="coerce")
    out["Ora registrazione"] = created
    cutoff = time(12,30)
    reintegro_dates = []
    for ts in created:
        if pd.isna(ts): reintegro_dates.append(pd.NaT); continue
        d = ts.date()
        if ts.time() > cutoff:
            d = d + timedelta(days=1)
        reintegro_dates.append(pd.Timestamp(d))
    out["Data reintegro"] = reintegro_dates
    return out


def make_excel(summary_df, detail_df, target_date):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        summary_df.to_excel(writer, index=False, sheet_name="Customer Connect")
        detail_df.to_excel(writer, index=False, sheet_name="Dettaglio")
        wb = writer.book
        header = wb.add_format({"bold":True,"border":1,"align":"center"})
        date_fmt = wb.add_format({"num_format":"dd/mm/yyyy"}); dt_fmt = wb.add_format({"num_format":"dd/mm/yyyy hh:mm"})
        for sheet_name, df_sheet in [("Customer Connect",summary_df),("Dettaglio",detail_df)]:
            ws = writer.sheets[sheet_name]
            for c,col in enumerate(df_sheet.columns):
                ws.write(0,c,col,header)
                vals=[len(str(x)) for x in df_sheet[col].head(300).tolist()]
                width=max([len(str(col))]+vals+[10])+2
                ws.set_column(c,c,min(width,36))
                if col in {"Data reintegro","Data intervento"}: ws.set_column(c,c,14,date_fmt)
                if col == "Ora registrazione": ws.set_column(c,c,20,dt_fmt)
            if len(df_sheet.columns)>0:
                ws.autofilter(0,0,len(df_sheet),len(df_sheet.columns)-1); ws.freeze_panes(1,0)
        info = wb.add_worksheet("Regola")
        info.write("A1","Customer Connect"); info.write("A2","Cutoff giornaliero"); info.write("B2","12:30")
        info.write("A3","Regola"); info.write("B3","Registrazioni entro le 12:30 = reintegro stesso giorno; dopo le 12:30 = reintegro giorno successivo")
        info.write("A4","Data estrazione"); info.write("B4",target_date.strftime("%d/%m/%Y"))
    buffer.seek(0); return buffer.getvalue()


def build_views(data, target_date):
    selected = data[pd.to_datetime(data["Data reintegro"], errors="coerce").dt.date == target_date].copy()
    if selected.empty:
        return selected, pd.DataFrame(columns=["Codice","Quantità"]), pd.DataFrame()
    selected["quantita"] = pd.to_numeric(selected.get("quantita"), errors="coerce").fillna(0)
    summary = (selected.groupby("codice", as_index=False)["quantita"].sum()
               .rename(columns={"codice":"Codice","quantita":"Quantità"}).sort_values("Codice"))
    detail_cols=[("intervento_id","Intervento"),("data_intervento","Data intervento"),("Ora registrazione","Ora registrazione"),("Data reintegro","Data reintegro"),("Struttura","Struttura"),("Cartella clinica","Cartella clinica"),("codice","Codice"),("descrizione","Descrizione"),("lotto","Lotto"),("quantita","Quantità"),("linea","Linea"),("agente","Agente")]
    existing=[a for a,_ in detail_cols if a in selected.columns]
    detail=selected[existing].copy().rename(columns={a:b for a,b in detail_cols})
    for col in ["Data intervento","Data reintegro","Ora registrazione"]:
        if col in detail.columns: detail[col]=pd.to_datetime(detail[col],errors="coerce")
    return selected, summary, detail


st.title("🔁 Customer Connect")
st.caption("Reintegri giornalieri con cutoff automatico alle 12:30. Visualizzi sempre sia oggi sia il giorno successivo.")
try:
    data=load_data()
except Exception as e:
    st.error(f"Errore lettura Customer Connect: {e}"); st.stop()
if data.empty:
    st.info("Nessun materiale disponibile per Customer Connect."); st.stop()

base_date = st.date_input("Data di riferimento", value=date.today())
next_date = base_date + timedelta(days=1)
st.info("Entro le 12:30 il materiale resta nel reintegro del giorno corrente; dopo le 12:30 viene già mostrato nella colonna del giorno successivo.")

tab_today, tab_next = st.tabs([f"📅 {base_date.strftime('%d/%m/%Y')}", f"➡️ {next_date.strftime('%d/%m/%Y')} · giorno successivo"])

for tab, target_date, label in [(tab_today,base_date,"Oggi / giorno selezionato"),(tab_next,next_date,"Giorno successivo")]:
    with tab:
        selected, summary, detail = build_views(data, target_date)
        st.subheader(f"{label} · reintegro {target_date.strftime('%d/%m/%Y')}")
        if selected.empty:
            st.warning("Nessun codice assegnato a questo reintegro.")
            continue
        m1,m2,m3=st.columns(3)
        m1.metric("Codici da reintegrare", summary["Codice"].nunique())
        m2.metric("Quantità totale", f"{summary['Quantità'].sum():g}")
        m3.metric("Interventi", selected["intervento_id"].nunique() if "intervento_id" in selected.columns else 0)
        excel=make_excel(summary,detail,target_date)
        st.download_button("⬇️ Scarica Excel Customer Connect", data=excel, file_name=f"Customer_Connect_{target_date.strftime('%Y%m%d')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary", use_container_width=True, key=f"download_cc_{target_date}")
        st.dataframe(summary,use_container_width=True,hide_index=True,height=360)
        with st.expander("Dettaglio interventi inclusi", expanded=False):
            st.dataframe(detail,use_container_width=True,hide_index=True,height=480,column_config={"Data intervento":st.column_config.DateColumn("Data intervento",format="DD/MM/YYYY"),"Data reintegro":st.column_config.DateColumn("Data reintegro",format="DD/MM/YYYY"),"Ora registrazione":st.column_config.DatetimeColumn("Ora registrazione",format="DD/MM/YYYY HH:mm")})
