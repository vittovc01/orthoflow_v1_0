# Setup Supabase per OrthoFlow

## 1. Crea progetto Supabase
Vai su Supabase e crea un nuovo progetto.

## 2. Esegui lo schema
Apri SQL Editor e incolla tutto il contenuto di:

`supabase_schema.sql`

poi esegui.

## 3. Crea file .env
Copia `.env.example` in `.env` e inserisci:

- SUPABASE_URL
- SUPABASE_ANON_KEY
- SUPABASE_SERVICE_ROLE_KEY
- USE_SUPABASE=true

## 4. Storage
Lo schema crea il bucket:

`orthoflow-documents`

per salvare:
- foto scarichi sala
- DDT
- offerte
- chiusure
- allegati vari

## 5. Pubblicazione web
Per pubblicare:
- Streamlit Cloud: più semplice
- Render/Railway: più professionale

## 6. Nota
La v0.5 mantiene anche SQLite locale come fallback.
Quando `USE_SUPABASE=false`, l'app funziona in locale.
Quando `USE_SUPABASE=true`, userà Supabase nei moduli integrati progressivamente.
