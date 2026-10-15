# Validazione prima dell'archivio OCR

> Snapshot iniziale V14. Per pipeline, privacy e comandi aggiornati vedere
> [V15](../ocr-validation-v15/README.md). I risultati iniziali sono conservati per confronto.

Stato: **BLOCKED. `OCR_REVIEW_ARCHIVE_ENABLED` resta disabilitato.**
Nessun SQL è stato applicato a staging o produzione durante questa consegna.

## 1. Valutatore e dati corretti

`evaluate_ocr.py` non istanzia Supabase e non salva revisioni. Il modo `live`
chiama `label_pipeline.analyze_labels`, esattamente il lettore di produzione,
tramite il servizio multi-documento e la sua aggregazione. `local` esercita i
componenti effettivi OpenCV/ZXing/Tesseract, senza simulare il modello di visione;
non è equivalente alla pipeline completa. `replay` ricalcola solo le metriche.

Installazione: ambiente Python dell'app (`pip install -r requirements-ci.txt`),
Tesseract inglese (`apt-get install tesseract-ocr`); il Dockerfile Render lo include.
PDF: rendering PyMuPDF già nelle dipendenze dell'app. Eseguire fuori dai log pubblici.

```csv
file,ref,lotto,scadenza,quantita
scarico01/foto1.jpg,04.200.016S,470L068,2036-02-01,1
scarico01/foto1.jpg,413.016S,46993P5,2035-01-01,2
scarico01/foto2.jpg,04.200.016S,470L068,2036-02-01,1
```

Il CSV contiene le etichette VISIBILI in ogni foto, con date ISO complete. Un
campo realmente illeggibile resta vuoto: non inventarlo. `quantita=2` espande due
etichette fisiche presenti in quella foto. Per riconoscere la stessa etichetta
ripresa da angolazioni diverse e misurare errori d'identità serve un sidecar:

```json
{"manual_truth_verified": false, "labels": [
 {"file":"scarico01/foto1.jpg","truth_index":0,"bbox":[60,470,365,530],"page":1,"case_id":"scarico01","physical_id":"pezzo1","conditions":[]},
 {"file":"scarico01/foto1.jpg","truth_index":1,"bbox":[370,530,680,600],"page":1,"case_id":"scarico01","physical_id":"pezzo2","conditions":[]},
 {"file":"scarico01/foto1.jpg","truth_index":2,"bbox":[370,600,680,670],"page":1,"case_id":"scarico01","physical_id":"pezzo3","conditions":[]},
 {"file":"scarico01/foto2.jpg","truth_index":0,"bbox":[50,300,500,500],"page":1,"case_id":"scarico01","physical_id":"pezzo1","conditions":["cross_photo_duplicate"]}
]}
```

`truth_index`: indice da zero per file dopo l'espansione delle quantità, nell'ordine
CSV. Box normalizzati 0–1000 sulla pagina originale; `page` parte da 1. Stesso
`physical_id` nello stesso `case_id` identifica lo stesso pezzo in più foto. REF,
lotto e scadenza devono coincidere fra queste annotazioni. Due veri pezzi dello
stesso lotto hanno ID diversi. Senza box il confronto è solo diagnostico e il gate
resta bloccato. I box di verità non vengono mai passati al lettore. Due operatori
devono controverificare verità, box, conteggio e identità prima di impostare
`manual_truth_verified=true`.

```bash
python evaluate_ocr.py --images /dati/ocr-test --truth /dati/ground_truth.csv \
  --annotations /dati/annotations.json --mode local --out /dati/report-local

# OPENAI_API_KEY configurata tramite secret manager/ambiente, mai nel comando o Git.
python evaluate_ocr.py --images /dati/ocr-test --truth /dati/ground_truth.csv \
  --annotations /dati/annotations.json --mode live --model gpt-4.1 --repeats 3 \
  --compare /dati/report-local/summary.json --out /dati/report-live

# Esempio riproducibile sui ritagli reali già privi di intestazione paziente:
python evaluate_ocr.py --images tests/fixtures/santa_lucia \
  --truth tests/evaluation/ground_truth.csv --annotations tests/evaluation/annotations.json \
  --mode local --out /tmp/ocr-local
```

Uscite: `report.csv` con errori silenziosi in prima riga e casi critici prima;
`problems.csv` e relativo elenco a schermo; `summary.json`; `predictions.json`
privo delle immagini e dei campi d'intestazione noti, riutilizzabile in replay.
Anche questi file possono contenere dati personali residui: conservarli privati.
Codici uscita: 0 accettato, 2 bloccato, 3 configurazione errata, 4 non eseguito.
Confronto rifiutato se cambia dataset; fingerprint dei sorgenti, verità e pipeline
nel riepilogo. Le tre ripetizioni live non triplicano la dimensione del campione.

Un errore silenzioso è un campo errato non marcato con avviso SPECIFICO o stato
incerto. Il semplice obbligo di conferma generale non lo nasconde. Campi mancanti,
etichette mancanti, falsi positivi, errori quantità e condizioni non segnalate sono
misurati separatamente; un falso positivo con campi sicuri genera errori silenziosi.
Il recall principale conta pezzi fisici distinti, non apparizioni; CSV riporta anche
ciascuna apparizione per controllare foto mancanti.

## 2. Casi limite

`tests/test_evaluate_ocr.py` verifica scoring, falso sicuro, localizzazione spaziale,
quantità, file identico duplicato, due foto diverse ambigue, conferma duplicato e
conferma pezzi distinti, lettura qualità effettiva su ritaglio scurito/sfocato,
classificazione di tutti gli avvisi. I test di `test_label_pipeline.py` includono
conflitti GS1/testo, REF discordanti, ritagli misti e conservazione GS1 quando AI
fallisce. Questi test dimostrano contratti e blocchi, non l'accuratezza del modello.

Il set reale deve includere tutte le condizioni annotate:
`overlap`, `touching`, `clipped`, `skew`, `glare`, `dark`, `blur`,
`cross_photo_duplicate`, `barcode_unreadable`, `text_unreadable`,
`barcode_text_conflict`. Per ciascuna usare foto effettive e verificare gli avvisi:
le euristiche di qualità non garantiscono di scoprire ogni riflesso/sovrapposizione.
Variare fornitori, telefoni, illuminazione, prospettiva e PDF multipagina; almeno
5 esempi per condizione consigliati. Ritagli isolati non sostituiscono foto complete.

Correzione trasversale: copie byte-identiche saltate; stesso REF/lotto fra foto
diverse blocca l'aggregazione finché l'operatore marca ogni riga come pezzo distinto
oppure indica `duplicate_of` con ID della prima riga (entrambi verificati). La prima
riga mantenuta va confermata distinta dalle altre righe mantenute. Nessuna deduplica
automatica per identità di lotto, che cancellerebbe pezzi realmente distinti.

## 3. Soglia proposta

- Zero errori silenziosi in **ogni** ripetizione live.
- Recall 100%, zero falsi positivi, quantità tutte esatte e risolte.
- Almeno 98% dei campi esatti e al massimo 15% da verificare, per impedire un
  apparente successo ottenuto segnando ogni campo come dubbio.
- 300 etichette fisiche distinte, almeno 50 scarichi indipendenti, foto complete,
  box indipendenti e verità controverificata, tutte le condizioni difficili
  rappresentate e segnalate, almeno 3 ripetizioni con versione modello registrata.
- Ogni errore silenzioso: analisi del ritaglio, regressione dedicata, correzione
  che svuoti o marchi il campo dubbio; ripetere l'intero benchmark.

Sono soglie di rilascio proposte, non prova matematica di assenza di errori futuri.
Zero su 300 casi indipendenti dà solo un limite superiore indicativo di circa 1%
(regola del tre); le etichette dello stesso scarico possono essere correlate.
Soglie CLI ridotte consentono diagnosi ma non superano il preflight produzione.

```bash
python scripts/check_ocr_acceptance.py /dati/report-live/summary.json \
  --pipeline-sha256 HASH_DELLA_VERSIONE_DA_DISTRIBUIRE
```

Il comando non modifica il flag. Richiede anche evidenza recente (30 giorni).

## 4. Checklist staging, accessi e privacy

- [ ] Flag assente/false sia su Render sia nei segreti Streamlit; backup verificato.
- [ ] Database staging separato; confronto manuale project ref, nessuna foto clinica
  reale necessaria per i test accessi. Non usare DATABASE_URL di produzione.
- [ ] Applicare SQL con connessione staging esplicita, controllo errori e log privato:

```bash
psql "$OCR_STAGING_DATABASE_URL" -X -v ON_ERROR_STOP=1 -f sql/ocr_review_archive.sql
psql "$OCR_STAGING_DATABASE_URL" -X -v ON_ERROR_STOP=1 -f scripts/verify_ocr_staging.sql
python scripts/verify_ocr_storage_staging.py \
  --staging-url https://REF_STAGING.supabase.co --staging-ref REF_STAGING
```

Il probe richiede `OCR_STAGING_SERVICE_KEY`, `OCR_STAGING_ANON_KEY`,
`OCR_STAGING_USER_A_JWT`, `OCR_STAGING_USER_B_JWT`, due utenti distinti reali.
Scrive solo un oggetto sintetico e lo cancella; non stampa chiavi/URL firmati.
Le SQL di verifica sono transazionali e fanno rollback dei dati sintetici.
Non è possibile dedurre staging dal nome del progetto: l'operatore deve verificare
il ref. I test non sono stati eseguiti contro un progetto remoto in questa consegna.

- [ ] `anon` e `authenticated` non leggono/scrivono alcun archivio: l'architettura
  è **server-only**, non accesso browser diretto per proprietario. Test A/B, anon,
  insert e select negati; log-in utente senza permesso app negato anche tramite UI.
  La service key bypassa RLS: autorizzazione del server va testata separatamente,
  incluse lettura e generazione URL per sessione di altro utente.
- [ ] Bucket `scarico-ocr-originals` privato; controllare anche policy preesistenti
  su `storage.objects` che potrebbero concedere accesso a tutti i bucket. Probe
  verifica download pubblico negato, A/B negati, firma negata, URL firmato valido
  poi scaduto. URL firmati sono bearer: chi li possiede può usarli fino a scadenza.
  TTL breve (es. 60 secondi), nessun URL in log, analytics o cache condivise.
- [ ] Test idempotenza/rollback applicativo, errore rete dopo salvataggio, nessuna
  movimentazione di magazzino generata dal solo archivio, backup e ripristino.
- [ ] Titolare/DPO approvano finalità, basi giuridiche art.6/9, ruoli e accordi
  responsabili art.28, fornitori/subresponsabili, localizzazione e trasferimenti,
  condizioni API modello e conservazione dei relativi log, accessi art.32 e
  necessità di DPIA art.35. Iniziali+cartella non rendono la foto anonima.
- [ ] Minimizzazione: valutare mascheramento dell'intestazione PRIMA dell'invio al
  modello e separazione dell'originale in area ad accesso ristretto. La versione
  iniziale V14 inviava pagine complete; V15 elimina tali chiamate e richiede
  approvazione locale di ogni ritaglio, con test sui payload. Restano da approvare
  finalità e condizioni dei fornitori prima di usare foto cliniche live.
- [ ] Retention documentata per originali, estratti, revisioni, report test, log,
  backup e copie fornitore. Nessun termine universale dedotto dal GDPR; definire
  scadenze e obblighi sanitari applicabili con titolare/DPO. Inventario senza delete:

```bash
psql "$OCR_STAGING_DATABASE_URL" -X -v cutoff='DATA_ISO_APPROVATA' \
  -f scripts/ocr_retention_inventory.sql
```

- [ ] Il registro attuale blocca UPDATE/DELETE: non esiste ancora un workflow di
  cancellazione privacy. Prima di attivare definire procedura privilegiata,
  autorizzata e auditata per eliminare foto e dati collegati, legal hold, backup,
  richieste interessati e prova di cancellazione. Non disabilitare il trigger con
  un cron generico. Nessuno script distruttivo automatico viene predisposto qui.
- [ ] Abilitazione solo dopo benchmark live accettato **e** tutti i punti di
  sicurezza/privacy chiusi; riesecuzione dopo modifiche di modello/pipeline.

Fonti ufficiali: [Storage privato](https://supabase.com/docs/guides/storage/buckets/fundamentals),
[RLS Storage](https://supabase.com/docs/guides/storage/security/access-control),
[URL firmati](https://supabase.com/docs/reference/python/storage-from-createsignedurl),
[GDPR, artt.5,6,9,28,32,35](https://eur-lex.europa.eu/eli/reg/2016/679/oj/eng).

## 5. Modello live e risultati

Vedere `RESULTS.md` e i report CSV/JSON allegati. Assenza di chiave o errore modello
non vale zero errori: metriche `null`/NON_MISURATI e uscita bloccante.
