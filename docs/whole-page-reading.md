# Lettura della foto intera, v15

## Gestione API v18

Gli errori 429 distinguono quota/fatturazione dai limiti temporanei usando soltanto
codici strutturati, senza esporre testo libero del provider. Quota esaurita: nessun
retry né fallback a un altro modello. Limite temporaneo: al massimo due retry,
rispettando Retry-After (secondi/data HTTP o millisecondi), massimo 60 secondi totali
di attesa. Se il servizio chiede un'attesa maggiore si restituisce l'avviso senza
anticipare la richiesta. I retry automatici SDK sono disattivati per questa sola
pipeline; DDT invariato. Non vengono inviati gli altri documenti del lotto quando
il servizio rimane bloccato. Una prima lettura riuscita resta disponibile con avviso
se la seconda fallisce. Il file resta nel caricatore della sessione Streamlit;
non viene persistita la pagina clinica per gestire il retry.

L'app non può ripristinare crediti o aumentare limiti di spesa: in quel caso serve
l'intervento del titolare dell'account API. Nessuna ricarica automatica.

Riferimenti ufficiali: https://developers.openai.com/api/docs/guides/rate-limits
e https://developers.openai.com/api/docs/guides/error-codes (20 ottobre 2026).

## Profilo v17

La lettura operativa usa `SCARICO_FULL_PAGE_MODEL` (default `gpt-6-astra`),
Responses API, `reasoning.effort=low` e dettaglio immagine `original`.
Il precedente `SCARICO_LABEL_MODEL` appartiene al lettore locale/per-ritaglio e
non seleziona il nuovo profilo. Il ruolo DDT mantiene `OPENAI_VISION_MODEL`.
Un 404 su Astra usa esplicitamente `gpt-5.4` con gli stessi parametri immagine;
il modello effettivo è riportato nei risultati. Altri errori non attivano downgrade.
Il lettore non torna silenziosamente a GPT-4.1. Il collaudo conserva i modelli
precedenti come opzioni di confronto e usa il nuovo profilo come default.

Il caso misurato con GPT-4.1 ha prodotto letture da 8 e 9 osservazioni, con valori
discordanti; il confronto v16 ne ha proposte 12. Questi risultati NON costituiscono
un collaudo superato. Il passaggio v17 deve essere validato con chiamate reali.

L'immagine mantiene tutta la pagina. Solo immagini eccedenti 28.000 patch o
65.535 pixel su un lato vengono ridimensionate uniformemente, senza ritagliare
prodotti o oscurare l'intestazione. I normali caricamenti mantengono le dimensioni.
Client con timeout di 180 secondi per le sole etichette; DDT invariato a 60 secondi.
Questo profilo privilegia la qualità e può aumentare tempi e costo API rispetto
al precedente GPT-4.1. Nessuna modifica a strumenti, cache, Pro mode o contratti
di output/registrazione.

Fonti ufficiali verificate il 17 ottobre 2026:
- https://developers.openai.com/api/docs/guides/images-vision
- https://developers.openai.com/api/docs/models/gpt-6-astra
- https://developers.openai.com/api/docs/models/gpt-5.4
- https://developers.openai.com/api/docs/guides/latest-model

La sezione seguente descrive il passaggio iniziale v15; la v16 aggiunge confronto
di occorrenze e posizioni, la v17 il profilo immagine/modello sopra descritto.

Il rilevatore locale della v14 limitava i pixel disponibili all'AI prima della
trascrizione. Un adesivo perso, inclinato o tagliato non poteva essere recuperato
dal modello. La v15 cambia l'ingresso della lettura, non soltanto il prompt.

`ai_ocr.analyze_document(mode='scarico_sala')` usa `whole_page_labels`:

1. Rende ogni pagina, rispettando EXIF. Invia la pagina intera a due richieste
   indipendenti con `store=False`, schema rigoroso e dettaglio alto.
2. Ogni richiesta conta e trascrive un'osservazione per adesivo fisico, anche se
   inclinato, verticale, sovrapposto o identico a un altro. Non raggruppa identità.
3. Associa le due liste uno a uno per posizione (IoU), non per REF o lotto.
   Valori discordanti restano vuoti con entrambe le letture disponibili. Le
   osservazioni presenti in una sola lettura rimangono visibili con avviso.
   Associazioni spaziali ambigue non producono consenso sui campi critici.
4. Dopo la prima lettura riuscita avvia il rilevatore locale per riscontri
   fotografici e GS1, sovrapponendolo alla seconda lettura API sequenziale.
   Il suo fallimento non elimina righe e non impedisce la lettura primaria.
   Un ritaglio viene conservato solo se validato localmente come prodotto e
   quasi coincidente con una singola osservazione. Nessun ritaglio AI arbitrario
   entra nell'archivio. In assenza di riscontri, si archiviano i dati prodotto
   senza fotografie. La pagina intera non è inclusa nell'estrazione restituita.

## Trasmissione e conservazione

Per richiesta esplicita dell'utente, l'intestazione non viene oscurata prima della
lettura AI. La pagina avvisa PRIMA dei pulsanti Analizza: il servizio AI riceve
anche gli eventuali dati clinici presenti nella foto. Lo schema non estrae campi
clinici; il testo libero source_text viene ricostruito soltanto dai tre campi
prodotto. `store=False` non è una dichiarazione di assenza assoluta di conservazione
da parte del provider: valgono le impostazioni e le condizioni dell'account API.

Il repository pubblico non contiene foto operative né dati paziente. L'archivio
OCR esistente continua a escludere pagina intera, intestazione e dati intervento.
La registrazione di un intervento resta un'azione separata dalla sola analisi.
GTIN resta tecnico e non bloccante; revisione, validazione server e protezioni
contro il doppio scarico restano operative. Nessuna modifica di schema/database.

## Verifica

`python -m pytest -q tests/test_whole_page_labels.py` verifica il flusso con client
simulato: immagine integrale in entrambe le richieste, otto adesivi conservati
anche con detector guasto, duplicati fisici, letture discordanti, recupero nella
seconda lettura, coordinate invalide e fallimenti API. Non misura l'accuratezza
del modello su fotografie reali. I test locali di geometria/privacy restano validi
per i soli ritagli d'archivio e per la pipeline precedente, non provano più che
l'intestazione sia esclusa dall'ingresso AI della v15.

La regressione live richiede il servizio AI configurato e il confronto con una
verità visiva indipendente; non si pubblicano risultati reali non eseguiti.
