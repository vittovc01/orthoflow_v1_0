
import os
from typing import Any, Dict, Optional
import pandas as pd

try:
    import streamlit as st
except Exception:
    st = None

from supabase import create_client


def secret(name: str, default=None):
    try:
        if st is not None and name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.getenv(name, default)


def sb():
    url = secret("SUPABASE_URL")
    key = secret("SUPABASE_SERVICE_KEY") or secret("SUPABASE_ANON_KEY") or secret("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("Supabase non configurato nei Secrets.")
    return create_client(str(url).rstrip("/"), str(key))


def df_select(table: str, order: str = "id", desc: bool = False) -> pd.DataFrame:
    res = sb().table(table).select("*").order(order, desc=desc).execute()
    return pd.DataFrame(res.data or [])


def insert_row(table: str, data: Dict[str, Any]) -> Dict[str, Any]:
    res = sb().table(table).insert(data).execute()
    return (res.data or [{}])[0]


def upsert_row(table: str, data: Dict[str, Any], on_conflict: Optional[str] = None):
    q = sb().table(table).upsert(data, on_conflict=on_conflict) if on_conflict else sb().table(table).upsert(data)
    return q.execute()


def registra_movimento(
    tipo_movimento: str,
    codice_magazzino: str,
    codice: str,
    lotto: str,
    quantita: float,
    descrizione: str = "",
    scadenza: str = None,
    origine: str = "CONTO DEPOSITO",
    riferimento_tipo: str = "",
    riferimento_id: str = "",
    note: str = "",
    utente: str = ""
):
    if not codice or not lotto:
        raise ValueError("Codice e lotto obbligatori.")
    return insert_row("movimenti_magazzino", {
        "tipo_movimento": tipo_movimento,
        "codice_magazzino": codice_magazzino,
        "codice": codice,
        "descrizione": descrizione,
        "lotto": lotto,
        "scadenza": scadenza or None,
        "quantita": float(quantita),
        "origine": origine,
        "riferimento_tipo": riferimento_tipo,
        "riferimento_id": str(riferimento_id or ""),
        "note": note,
        "utente": utente,
    })


def carica_ddt_su_magazzino(ddt_id: int, codice_magazzino: str, righe: pd.DataFrame, origine: str, utente: str = ""):
    n = 0
    for _, r in righe.iterrows():
        codice = str(r.get("codice", "")).strip()
        lotto = str(r.get("lotto", "")).strip()
        if not codice or not lotto:
            continue
        qta = float(r.get("quantita", 1) or 1)
        registra_movimento(
            tipo_movimento="CARICO_DDT",
            codice_magazzino=codice_magazzino,
            codice=codice,
            lotto=lotto,
            quantita=qta,
            descrizione=str(r.get("descrizione", "") or ""),
            scadenza=str(r.get("scadenza", "") or "") or None,
            origine=origine,
            riferimento_tipo="DDT",
            riferimento_id=str(ddt_id),
            utente=utente,
        )
        n += 1
    return n


def scarica_intervento_da_magazzino(intervento_id: int, codice_magazzino: str, righe: pd.DataFrame, utente: str = ""):
    n = 0
    anomalie = []
    for _, r in righe.iterrows():
        codice = str(r.get("codice", "")).strip()
        lotto = str(r.get("lotto", "")).strip()
        if not codice or not lotto:
            continue
        qta = float(r.get("quantita", 1) or 1)
        giac = sb().table("giacenze").select("*").eq("codice_magazzino", codice_magazzino).eq("codice", codice).eq("lotto", lotto).execute().data
        disponibile = float(giac[0]["quantita"]) if giac else 0
        if disponibile < qta:
            msg = f"Giacenza insufficiente {codice} lotto {lotto}: disponibile {disponibile}, richiesta {qta}"
            anomalie.append(msg)
            insert_row("anomalie", {
                "tipo": "GIACENZA_INSUFFICIENTE",
                "gravita": "Alta",
                "descrizione": msg,
                "stato": "Aperta",
            })
        registra_movimento(
            tipo_movimento="SCARICO_INTERVENTO",
            codice_magazzino=codice_magazzino,
            codice=codice,
            lotto=lotto,
            quantita=-abs(qta),
            descrizione=str(r.get("descrizione", "") or ""),
            scadenza=str(r.get("scadenza", "") or "") or None,
            origine=str(r.get("origine", "CONTO DEPOSITO") or "CONTO DEPOSITO"),
            riferimento_tipo="INTERVENTO",
            riferimento_id=str(intervento_id),
            utente=utente,
        )
        n += 1
    return n, anomalie
