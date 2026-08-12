# OCR AI Setup — OrthoFlow Control Tower

OrthoFlow usa OpenAI Responses API con input immagine e output strutturato per precompilare lo scarico sala.

## Streamlit Community Cloud

Apri **Manage app → Settings → Secrets** e aggiungi:

```toml
OPENAI_API_KEY = "sk-..."
OPENAI_VISION_MODEL = "gpt-5-mini"
ENABLE_AI_OCR = true
```

Non salvare mai la chiave API nel repository GitHub.

## Scarico sala

L'OCR AI prova a estrarre:

- struttura/clinica;
- numero cartella clinica;
- data intervento;
- chirurgo;
- codice REF esatto;
- lotto LOT;
- scadenza;
- descrizione;
- produttore;
- quantità;
- sterile/non sterile;
- livello di confidenza e warning.

Il codice Johnson viene mantenuto esattamente come letto: per esempio `413.050S` resta distinto da `413.050`.

Le immagini vengono inviate con dettaglio alto. La chiamata Responses API usa `store=False`. L'output AI è solo una precompilazione: prima dello scarico definitivo l'operatore deve verificare codice, lotto, scadenza e quantità nella tabella modificabile.

## Privacy

Le immagini di sala possono contenere dati sanitari o identificativi. Prima dell'uso in produzione verificare che il trattamento, i contratti, i consensi e le impostazioni di conservazione/residenza dati siano adeguati alle policy aziendali e agli obblighi applicabili.
