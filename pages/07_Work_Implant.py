import io
import os
from datetime import datetime

import pandas as pd
import streamlit as st
from supabase import create_client

st.set_page_config(page_title="Work Implant · OrthoFlow", page_icon="📄", layout="wide")


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


def sb():
    return client()


def clean(v):
    if v is None:
        return ""
    if isinstance(v, float) and pd.isna(v):
        return ""
    return str(v).strip()


def user():
    return clean(st.session_state.get("user"))


def role():
    return clean(st.session_state.get("ruolo"))


if not user():
    st.warning("Accedi prima a OrthoFlow Control Tower.")
    st.stop()

if role() not in {"Admin", "Amministrazione"}:
    st.error("Questa pagina è riservata ad Admin e Amministrazione.")
    st.stop()


@st.cache_data(ttl=60)
def load_work_implant():
    righe = (sb().table("righe_intervento").select("*")
             .order("id", desc=True).limit(5000).execute().data or [])
    interventi = (sb().table("interventi").select("*")
                  .order("id", desc=True).limit(2000).execute().data or [])

    if not righe:
        return pd.DataFrame()

    rdf = pd.DataFrame(righe)
    idf = pd.DataFrame(interventi)
    if idf.empty or "id" not in idf.columns:
        return rdf

    keep = [c for c in [
        "id", "data_intervento", "codice_cliente", "cliente", "struttura",
        "cartella_clinica", "chirurgo", "agente", "linea", "magazzino_scarico"
    ] if c in idf.columns]
    idf = idf[keep].copy()
    idf = idf.rename(columns={"id": "intervento_id"})

    out = rdf.merge(idf, on="intervento_id", how="left", suffixes=("", "_intervento"))

    if "cliente" in out.columns:
        out["Struttura"] = out["cliente"].fillna("").astype(str)
    elif "struttura" in out.columns:
        out["Struttura"] = out["struttura"].fillna("").astype(str)
    else:
        out["Struttura"] = ""

    if "struttura" in out.columns:
        mask = out["Struttura"].str.strip().eq("")
        out.loc[mask, "Struttura"] = out.loc[mask, "struttura"].fillna("").astype(str)

    out["Cartella clinica"] = out.get("cartella_clinica", "")
    return out


def make_excel(df_export):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        df_export.to_excel(writer, index=False, sheet_name="Work Implant")
        workbook = writer.book
        worksheet = writer.sheets["Work Implant"]
        header_fmt = workbook.add_format({
            "bold": True,
            "border": 1,
            "align": "center",
            "valign": "vcenter",
        })
        money_fmt = workbook.add_format({"num_format": "€ #,##0.00"})
        date_fmt = workbook.add_format({"num_format": "dd/mm/yyyy"})
        for col_num, value in enumerate(df_export.columns.values):
            worksheet.write(0, col_num, value, header_fmt)
            sample = df_export[value].astype(str).head(200) if value in df_export else pd.Series(dtype=str)
            max_len = max([len(str(value))] + [len(x) for x in sample.tolist()])
            worksheet.set_column(col_num, col_num, min(max(max_len + 2, 10), 35))
            if value in {"Prezzo", "Totale"}:
                worksheet.set_column(col_num, col_num, 14, money_fmt)
            if value == "Data intervento":
                worksheet.set_column(col_num, col_num, 14, date_fmt)
        worksheet.freeze_panes(1, 0)
        worksheet.autofilter(0, 0, len(df_export), max(len(df_export.columns) - 1, 0))
    buffer.seek(0)
    return buffer.getvalue()


st.title("📄 Work Implant")
st.caption("Elenco completo dei materiali impiantati con struttura, cartella clinica e download immediato in Excel.")

try:
    data = load_work_implant()
except Exception as e:
    st.error(f"Errore lettura Work Implant: {e}")
    st.stop()

if data.empty:
    st.info("Nessuna riga Work Implant disponibile.")
    st.stop()

c1, c2, c3 = st.columns([2, 2, 2])
filtro_struttura = c1.text_input("Filtra struttura")
filtro_cartella = c2.text_input("Filtra cartella clinica")
filtro_codice = c3.text_input("Filtra codice")

filtered = data.copy()
if filtro_struttura:
    filtered = filtered[filtered["Struttura"].astype(str).str.contains(filtro_struttura, case=False, na=False)]
if filtro_cartella:
    filtered = filtered[filtered["Cartella clinica"].astype(str).str.contains(filtro_cartella, case=False, na=False)]
if filtro_codice and "codice" in filtered.columns:
    filtered = filtered[filtered["codice"].astype(str).str.contains(filtro_codice, case=False, na=False)]

columns_map = [
    ("intervento_id", "Intervento"),
    ("data_intervento", "Data intervento"),
    ("Struttura", "Struttura"),
    ("Cartella clinica", "Cartella clinica"),
    ("codice", "Codice"),
    ("descrizione", "Descrizione"),
    ("lotto", "Lotto"),
    ("scadenza", "Scadenza"),
    ("quantita", "Quantità"),
    ("prezzo", "Prezzo"),
    ("totale", "Totale"),
    ("agente", "Agente"),
    ("linea", "Linea"),
    ("chirurgo", "Chirurgo"),
    ("magazzino_scarico", "Magazzino"),
]
selected_cols = [src for src, _ in columns_map if src in filtered.columns]
display = filtered[selected_cols].copy()
display = display.rename(columns={src: dst for src, dst in columns_map})

if "Data intervento" in display.columns:
    display["Data intervento"] = pd.to_datetime(display["Data intervento"], errors="coerce")
if "Scadenza" in display.columns:
    display["Scadenza"] = pd.to_datetime(display["Scadenza"], errors="coerce")

m1, m2, m3 = st.columns(3)
m1.metric("Righe", len(display))
m2.metric("Interventi", display["Intervento"].nunique() if "Intervento" in display.columns else 0)
m3.metric("Strutture", display["Struttura"].nunique() if "Struttura" in display.columns else 0)

excel_bytes = make_excel(display)
filename = f"Work_Implant_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
st.download_button(
    "⬇️ Scarica Excel Work Implant",
    data=excel_bytes,
    file_name=filename,
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    type="primary",
    use_container_width=True,
)

st.subheader("Lista Work Implant")
st.dataframe(
    display,
    use_container_width=True,
    hide_index=True,
    height=620,
    column_config={
        "Data intervento": st.column_config.DateColumn("Data intervento", format="DD/MM/YYYY"),
        "Scadenza": st.column_config.DateColumn("Scadenza", format="DD/MM/YYYY"),
        "Prezzo": st.column_config.NumberColumn("Prezzo", format="€ %.2f"),
        "Totale": st.column_config.NumberColumn("Totale", format="€ %.2f"),
    },
)
