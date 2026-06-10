# Checklist pubblicazione OrthoFlow v1.0

## 1. GitHub
- Crea repository `orthoflow-control-tower`
- Carica tutti i file dello ZIP

## 2. Supabase
- Crea progetto gratuito
- Apri SQL Editor
- Esegui `supabase_schema.sql`
- Copia URL e API keys

## 3. Streamlit Cloud o Render
### Streamlit Cloud
- New App
- Repository GitHub
- Main file: `app.py`
- Secrets:
  - OPENAI_API_KEY
  - ENABLE_AI_OCR=true
  - SUPABASE_URL
  - SUPABASE_ANON_KEY
  - USE_SUPABASE=true

### Render
- Usa `render.yaml`
- Inserisci variabili ambiente

## 4. Primo avvio
- Login admin/admin
- Importa ANAGRA
- Importa giacenze
- Crea offerte e importa prezzi
- Testa scarico sala
- Testa Customer Connect

## 5. Test obbligatori
- DDT conto deposito
- DDT Loan conto visione
- Scarico DePuy Synthes
- Scarico Smith & Nephew
- WI
- Customer Connect
- Anomalie
