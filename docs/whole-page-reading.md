# Lettura della foto intera, v15

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
4. Solo dopo la lettura prova il rilevatore locale per riscontri fotografici e
   GS1. Il suo fallimento non elimina righe e non impedisce la lettura primaria.
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
