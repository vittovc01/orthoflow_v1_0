"""Director-only recognition acceptance surface. No stock/database writes."""
import json
import os
import tempfile
from pathlib import Path

import streamlit as st

permissions = set(st.session_state.get('permessi', []) or [])
if not st.session_state.get('user') or not (
    str(st.session_state.get('ruolo', '')).strip() == 'Admin' or 'DIREZIONE' in permissions
):
    st.error('Accesso non autorizzato.')
    st.stop()

from openai import OpenAI
from ai_ocr import ai_status, _secret, ITEM_PROPERTIES, ITEM_REQUIRED, _parse_response
from whole_page_runtime import refresh_ocr_modules
refresh_ocr_modules()
from whole_page_labels import analyze_labels, WholePageReadError
from label_pipeline import PIPELINE_VERSION

st.title('🔬 Collaudo OCR')
st.caption(PIPELINE_VERSION)
st.info('Solo riconoscimento: questa pagina non crea interventi e non scarica materiali.')
st.info('La lettura invia la foto intera al servizio AI, inclusa l’eventuale intestazione. Per collaudi usare foto senza dati paziente.')
status = ai_status()
if not status['enabled']:
    st.error('OCR non configurato: ' + ', '.join(status['missing']))
    st.stop()

model = st.selectbox('Modello per il collaudo', list(dict.fromkeys([
    status['model'], 'gpt-4.1', 'gpt-5-mini'
])))
upload = st.file_uploader('Foto originale da verificare', type=['jpg','jpeg','png','webp','pdf'])
if st.button('Analizza senza scaricare', disabled=upload is None):
    if len(upload.getvalue()) > 20 * 1024 * 1024:
        st.error('Massimo 20 MB per il collaudo.')
        st.stop()
    path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=Path(upload.name).suffix.lower(), delete=False) as f:
            f.write(upload.getvalue())
            path = f.name
        client = OpenAI(api_key=_secret('OPENAI_API_KEY'), timeout=60, max_retries=1)
        with st.spinner('Due letture indipendenti della foto intera…'):
            result = analyze_labels(path, client, model,
                {'type':'object','properties':ITEM_PROPERTIES,'required':ITEM_REQUIRED,
                 'additionalProperties':False}, _parse_response)
        st.session_state['ocr_acceptance_result'] = result
        st.session_state['ocr_acceptance_model'] = model
    except Exception as exc:
        st.session_state.pop('ocr_acceptance_result', None)
        reason = exc.public_reason if isinstance(exc, WholePageReadError) else type(exc).__name__
        st.error('Collaudo interrotto (' + reason + '). Nessun movimento di magazzino effettuato.')
    finally:
        if path:
            os.unlink(path)

result = st.session_state.get('ocr_acceptance_result')
if result and result.get('pipeline_version') != PIPELINE_VERSION:
    st.session_state.pop('ocr_acceptance_result',None)
    st.info('Pipeline aggiornata: riesegui il collaudo sulla foto caricata.')
    result = None
if result:
    st.caption('Modello utilizzato: ' + st.session_state['ocr_acceptance_model'])
    st.metric('Etichette individuate', len(result['items']))
    for warning in result.get('detection_warnings', []):
        st.warning(warning)
    keys = ['label_id','code','lot','expiry','description','manufacturer','warning','bbox','rotation']
    st.dataframe([{k:r.get(k) for k in keys} for r in result['items']], hide_index=True)
    for row in result['items']:
        with st.expander(str(row['label_id']) + ' · ' + str(row.get('code') or 'REF da verificare')):
            if row.get('crop_data_url'):
                st.image(row['crop_data_url'])
            st.json({k:v for k,v in row.items() if k != 'crop_data_url'})
    st.download_button('Scarica evidenze del collaudo', json.dumps(result,ensure_ascii=False,indent=2),
                       file_name='ocr-acceptance.json', mime='application/json')
