import io
import os
from datetime import datetime, timedelta

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
             .order("id", desc=True).limit(10000).execute().data or [])
    interventi = (sb().table("interventi").select("*")
                  .order("id", desc=True).limit(5000).execute().data or [])

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
    idf = idf[keep].copy().rename(columns={"id": "intervento_id"})

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
    out["data_intervento"] = pd.to_datetime(out.get("data_intervento"), errors="coerce")
    return out


def operational_week_start(value):
    """Lun-Ven appartengono alla settimana corrente; sab/dom passano al lunedì successivo."""
    if pd.isna(value):
        return pd.NaT
    d = pd.Timestamp(value).normalize()
    weekday = d.weekday()  # lun=0 ... dom=6
    if weekday <= 4:
        return d - pd.Timedelta(days=weekday)
    return d + pd.Timedelta(days=(7 - weekday))


def week_label(week_start):
    if pd.isna(week_start):
        return "Data non disponibile"
    start = pd.Timestamp(week_start)
    end = start + pd.Timedelta(days=4)
    prior_sat = start - pd.Timedelta(days=2)
    return f"Settimana {start.strftime('%d/%m/%Y')} - {end.strftime('%d/%m/%Y')} · dal sabato {prior_sat.strftime('%d/%m')} incluso"


def export_columns(frame):
    columns_map = [
        ("Settimana", "Settimana"),
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
    selected = [src for src, _ in columns_map if src in frame.columns]
    out = frame[selected].copy().rename(columns={src: dst for src, dst in columns_map})
    if "Data intervento" in out.columns:
        out["Data intervento"] = pd.to_datetime(out["Data intervento"], errors="coerce")
    if "Scadenza" in out.columns:
        out["Scadenza"] = pd.to_datetime(out["Scadenza"], errors="coerce")
    return out


def write_sheet(writer, sheet_name, df_export):
    safe_name = sheet_name[:31]
    df_export.to_excel(writer, index=False, sheet_name=safe_name)
    workbook = writer.book
    worksheet = writer.sheets[safe_name]
    header_fmt = workbook.add_format({"bold": True, "border": 1, "align": "center", "valign": "vcenter"})
    money_fmt = workbook.add_format({"num_format": "€ #,##0.00"})
    date_fmt = workbook.add_format({"num_format": "dd/mm/yyyy"})

    for col_num, value in enumerate(df_export.columns.values):
        worksheet.write(0, col_num, value, header_fmt)
        sample = df_export[value].head(300) if value in df_export.columns else pd.Series(dtype=str)
        lengths = [len(str(value))] + [len(str(x)) for x in sample.tolist()]
        max_len = max(lengths) if lengths else 10
        worksheet.set_column(col_num, col_num, min(max(max_len + 2, 10), 40))
        if value in {"Prezzo", "Totale"}:
            worksheet.set_column(col_num, col_num, 14, money_fmt)
        if value in {"Data intervento", "Scadenza"}:
            worksheet.set_column(col_num, col_num, 14, date_fmt)

    worksheet.freeze_panes(1, 0)
    if len(df_export.columns) > 0:
        worksheet.autofilter(0, 0, len(df_export), len(df_export.columns) - 1)


def make_excel(df_export):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        write_sheet(writer, "Tutti", df_export)
        if "Linea" in df_export.columns:
            trauma = df_export[df_export["Linea"].astype(str).str.upper().eq("TRAUMA")]
            protesica = df_export[df_export["Linea"].astype(str).str.upper().eq("PROTESICA")]
            write_sheet(writer, "TRAUMA", trauma)
            write_sheet(writer, "PROTESICA", protesica)
    buffer.seek(0)
    return buffer.getvalue()


st.title("📄 Work Implant")
st.caption("Lista settimanale dei materiali impiantati, separata per TRAUMA e PROTESICA. Gli interventi del sabato e della domenica vengono assegnati alla settimana successiva.")

try:
    data = load_work_implant()
except Exception as e:
    st.error(f"Errore lettura Work Implant: {e}")
    st.stop()

if data.empty:
    st.info("Nessuna riga Work Implant disponibile.")
    st.stop()

data["Settimana_start"] = data["data_intervento"].apply(operational_week_start)
data["Settimana"] = data["Settimana_start"].apply(week_label)

# Filtri facoltativi: la lista completa è visibile subito anche senza compilare nulla.
c1, c2, c3 = st.columns(3)
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

filtered = filtered.sort_values(["Settimana_start", "data_intervento", "intervento_id"], ascending=[False, False, False], na_position="last")
display_all = export_columns(filtered)

m1, m2, m3 = st.columns(3)
m1.metric("Righe", len(display_all))
m2.metric("Interventi", display_all["Intervento"].nunique() if "Intervento" in display_all.columns else 0)
m3.metric("Strutture", display_all["Struttura"].nunique() if "Struttura" in display_all.columns else 0)

excel_bytes = make_excel(display_all)
filename = f"Work_Implant_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
st.download_button(
    "⬇️ Scarica Excel Work Implant",
    data=excel_bytes,
    file_name=filename,
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    type="primary",
    use_container_width=True,
)

st.divider()

week_values = [x for x in filtered["Settimana_start"].dropna().drop_duplicates().tolist()]
if not week_values:
    st.info("Nessuna data intervento valida da visualizzare.")
    st.stop()

for week_start in week_values:
    week_df = filtered[filtered["Settimana_start"] == week_start].copy()
    st.subheader(f"📅 {week_label(week_start)}")

    trauma = week_df[week_df.get("linea", "").astype(str).str.upper().eq("TRAUMA")] if "linea" in week_df.columns else week_df.iloc[0:0]
    protesica = week_df[week_df.get("linea", "").astype(str).str.upper().eq("PROTESICA")] if "linea" in week_df.columns else week_df.iloc[0:0]
    altre = week_df[~week_df.index.isin(trauma.index) & ~week_df.index.isin(protesica.index)]

    tab_trauma, tab_protesica, tab_altre = st.tabs([
        f"🦴 TRAUMA ({trauma['intervento_id'].nunique() if not trauma.empty else 0})",
        f"🦿 PROTESICA ({protesica['intervento_id'].nunique() if not protesica.empty else 0})",
        f"📦 ALTRE LINEE ({altre['intervento_id'].nunique() if not altre.empty else 0})",
    ])

    with tab_trauma:
        if trauma.empty:
            st.info("Nessun intervento TRAUMA in questa settimana.")
        else:
            st.dataframe(export_columns(trauma), use_container_width=True, hide_index=True, height=min(520, 110 + len(trauma) * 35),
                         column_config={"Data intervento": st.column_config.DateColumn("Data intervento", format="DD/MM/YYYY"), "Scadenza": st.column_config.DateColumn("Scadenza", format="DD/MM/YYYY"), "Prezzo": st.column_config.NumberColumn("Prezzo", format="€ %.2f"), "Totale": st.column_config.NumberColumn("Totale", format="€ %.2f")})

    with tab_protesica:
        if protesica.empty:
            st.info("Nessun intervento PROTESICA in questa settimana.")
        else:
            st.dataframe(export_columns(protesica), use_container_width=True, hide_index=True, height=min(520, 110 + len(protesica) * 35),
                         column_config={"Data intervento": st.column_config.DateColumn("Data intervento", format="DD/MM/YYYY"), "Scadenza": st.column_config.DateColumn("Scadenza", format="DD/MM/YYYY"), "Prezzo": st.column_config.NumberColumn("Prezzo", format="€ %.2f"), "Totale": st.column_config.NumberColumn("Totale", format="€ %.2f")})

    with tab_altre:
        if altre.empty:
            st.info("Nessun intervento di altre linee in questa settimana.")
        else:
            st.dataframe(export_columns(altre), use_container_width=True, hide_index=True, height=min(520, 110 + len(altre) * 35),
                         column_config={"Data intervento": st.column_config.DateColumn("Data intervento", format="DD/MM/YYYY"), "Scadenza": st.column_config.DateColumn("Scadenza", format="DD/MM/YYYY"), "Prezzo": st.column_config.NumberColumn("Prezzo", format="€ %.2f"), "Totale": st.column_config.NumberColumn("Totale", format="€ %.2f")})
