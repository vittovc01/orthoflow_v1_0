# OCR AI Setup - OrthoFlow v0.6

Questa versione integra OCR AI tramite OpenAI Vision.

## Variabili ambiente

Imposta:

```env
OPENAI_API_KEY=sk-...
OPENAI_VISION_MODEL=gpt-4.1-mini
ENABLE_AI_OCR=true
```

## Cosa fa

### Scarichi sala
- Legge foto scarico sala
- Estrae codice REF
- Estrae lotto LOT
- Estrae scadenza
- Estrae produttore
- Riconosce J&J / DePuy Synthes / Synthes
- Esclude Smith & Nephew e altri competitor
- Genera righe intervento
- Genera Work Implant
- Prepara Customer Connect, escludendo Loan

### DDT
- Legge DDT foto
- Estrae numero DDT, data, cliente, motivo trasporto
- Riconosce Conto Visione / Loan
- Carica materiale in magazzino o in Loan tracking
- Se Loan viene impiantato entra nel WI ma non nel reintegro

## Nota

La validazione umana resta obbligatoria prima del salvataggio: l'app mostra le righe AI in tabella modificabile.
