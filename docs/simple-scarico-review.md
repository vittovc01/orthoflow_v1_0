# Scarico Sala AI: revisione semplificata

Il sistema riconosce le etichette; l'operatore controlla REF, lotto, scadenza e quantità. La pagina usa una sola conferma: «Ho controllato REF, lotto, scadenza e quantità di tutte le righe».

## Comportamento

- GTIN e DataMatrix restano evidenze tecniche. GTIN vuoto, non letto, non valido o non censito non impedisce di confermare. `None`, NaN numerico, stringa `nan`, NaT e valori nulli del dataframe vengono normalizzati. Il GTIN non è nell'editor né nel modulo manuale e non può essere sovrascritto dagli edit del client.
- Se manca il REF OCR e un GTIN valido trova una corrispondenza in `articoli_gtin`, il sistema propone quel REF, con provenienza distinta. Non sovrascrive una lettura OCR presente o un REF modificato/svuotato dall'operatore. Catalogo indisponibile, REF non censito o discordanza generano avvisi morbidi.
- L'editor è fuori dal modulo di conferma: modifiche, aggiunte e cancellazioni entrano subito nello stato della sessione. Sono modificabili REF, lotto, scadenza e quantità intera positiva. Identità, ritagli e provenienza rimangono assegnati dal server. Il modulo manuale funziona anche senza un documento caricato e non genera anteprime della pagina intera.
- Gli errori compaiono sulla sola riga interessata, con indicatore rosso e messaggi `REF, lotto LOT: campo mancante/non valido`. Nessuna riga incompleta viene scaricata silenziosamente: correggerla oppure eliminarla/escluderla per procedere con le altre.
- Il numero di etichette parte dalle righe rilevate e aggiunte, al netto delle righe escluse/eliminate. È modificabile; una differenza viene mostrata con segno e registrata come avviso, senza blocco. Numero di righe e quantità di pezzi sono distinti: una riga può avere quantità 2 dopo la correzione dell'operatore.
- Stesso REF e lotto su righe distinte sommano le quantità; lotti diversi rimangono separati. La verifica delle foto ripetute è un avviso incluso nell'unica conferma globale.
- Il wrapper della pagina non intercetta più il submit attraverso la vecchia chiave nascosta `scarico_verified`.

## Registro delle correzioni

Ogni aggiunta, modifica o cancellazione produce un record con identità della riga, campo, valore precedente, valore corretto, operazione, metodo `manuale`, utente della sessione autenticata e timestamp UTC. Sono conservate anche correzioni intermedie; un rerun senza cambiamenti non genera nuovi record. I record non contengono immagini.

Prima del salvataggio il registro vive nella sessione ed è consultabile nella pagina. Alla conferma viene trasmesso nella stessa transazione dell'intervento e conservato nel suo `audit_log`, insieme al conteggio dichiarato e alla differenza. Non si tratta di archiviazione OCR né di caricamento degli originali. Chiudere la sessione senza salvare l'intervento non costituisce un salvataggio permanente delle modifiche.

## Contratto server e pubblicazione

La pagina invia `review_contract_version=2` alla RPC verificata. Per questo contratto la quantità positiva può essere diversa dal numero di identificativi di etichetta. La RPC controlla invece che identità, quantità, REF, lotto e scadenza corrispondano al manifesto della revisione; rifiuta valori alterati e mantiene il controllo delle identità duplicate. Il contratto precedente rimane compatibile. Prezzi/giacenze discordanti continuano a generare anomalie senza sostituire lotti o scalare stock non corrispondenti.

**Non pubblicare la sola interfaccia sul vecchio SQL.** Applicare prima la definizione aggiornata in `sql/verified_physical_label_discharge.sql` su un database staging separato, poi provarvi la pagina e il salvataggio con quantità modificate. La produzione non è stata modificata. La PR resta in bozza, senza merge o deployment.

`archive_enabled=False` resta forzato nella pagina. `OCR_REVIEW_ARCHIVE_ENABLED` non viene attivato; nessun originale viene archiviato. Un'eventuale riattivazione futura dell'archivio richiede il suo collaudo separato, compresa l'identità dopo aggiunte/cancellazioni.

## Verifiche riproducibili

```bash
python -m pytest -q tests/test_review_editor.py tests/test_pages_smoke.py tests/test_ocr_review.py tests/test_label_pipeline.py tests/test_gtin_catalog_import.py tests/test_literal_evidence_conflicts.py
python tests/test_scarico_form.py
npm ci --prefix tools/gtin-staging --ignore-scripts
node tools/gtin-staging/test-review.mjs
```

Le prove usano dati sintetici e PostgreSQL 17 isolato. Coprono GTIN assente/NaN/non censito, proposta del REF da catalogo, edit di quattro campi, aggiunta/cancellazione direttamente dall'editor e dal modulo, conteggio precompilato, avviso discordanza, conferma unica, errori REF+lotto, riga rossa, protezione della provenienza e registro delle correzioni. Il test SQL verifica quantità 2 su una sola riga, audit persistente, conteggio discordante non bloccante e rifiuto di quantità alterate; ripete anche i precedenti test dello scarico fisico. Sono state eseguite inoltre le regressioni privacy e le suite di accessi/API.

Restano il collaudo su staging ospitato, la revisione della PR e l'autorizzazione esplicita prima di qualsiasi applicazione SQL o deployment in produzione. Il piano/progetto staging ospitato non viene cambiato da questa modifica.
