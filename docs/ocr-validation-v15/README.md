# DataMatrix, catalogo GTIN e privacy prima del modello

**Archivio disattivato. Nessun test con modello live eseguito in questa consegna.**
Queste modifiche estendono PR #39; vedere anche `RESULTS.md` e i CSV.

## 1. Decodifica e acquisizione

`datamatrix_reader.py` usa esclusivamente pixel reali: soglie globali, contrasto
CLAHE, Otsu, soglie adattive 11/21/31, scale .75/1.5/2/3/4, rotazioni cardinali
PRIMA della soglia e del ricampionamento, piccole inclinazioni ±4/±8°, ritagli
quadrati misurati e rettifica prospettica. Ogni payload conserva il metodo e passa
il parser GS1/check digit. Nessun carattere viene ricostruito. Il decoder congela il primo gruppo di payload validi; ritagli con più simboli devono essere esclusi o separati nella revisione locale. I tentativi sono
limitati e non usano immagini generate. Decodifica prima i ritagli per etichetta,
non una pagina ridotta dal modello. `local_label_reader.py` riconosce anche una
foto già ritagliata su un solo adesivo con GS1 valido, evitando di dividerla in
più regioni.

L'ingrandimento può cambiare la fase di campionamento utile al decoder, ma non
restituisce dettagli persi per compressione/sfocatura. Il test di risoluzione usa
SOLO la risoluzione nativa disponibile e riduzioni controllate: un upscaling non
è un originale a risoluzione maggiore e non dimostra una soglia di acquisizione.

```bash
python scripts/benchmark_datamatrix.py --images /dati/foto \
 --truth /dati/ground_truth.csv --annotations /dati/annotations.json \
 --out /dati/risoluzione.csv
```

I box della verità servono allo scoring, mai al lettore. Il CSV riporta dimensioni
sorgente/ridotte, regioni locali, payload decodificati, coppie lotto/scadenza esatte,
payload errati e tasso rispetto alle etichette presenti. Il test è end-to-end
locale (include eventuali perdite della localizzazione), non solo un decoder con
ritagli corretti forniti a mano. Il denominatore resta quello della verità.

L'interfaccia mostra prima del modello dimensioni e avvisi locali. Obiettivi
**provvisori, non soglie clinicamente validate**: lato lungo foto >=2400 px e lato
del finder più piccolo >=64 px. Non bastano da soli: se GS1 non viene decodificato
si richiede una nuova foto ravvicinata, nitida, senza riflessi. La foto completa
900×1600 disponibile non dimostra alcuna risoluzione minima per decodifica completa.
Servono originali di acquisizione più definiti, non copie ingrandite.

Avvisi di ridimensionamento: dimensioni EXIF originali maggiori di quelle correnti,
software screenshot/messaggistica nei metadati. Avvisi di possibile compressione:
quantizzazione JPEG elevata. Metadati assenti non provano né escludono compressione;
non viene affermato che ogni JPEG o foto piccola sia necessariamente ricompressa.

## 2. CSV del catalogo e tabella articoli_gtin

Serve un **catalogo ufficiale del fornitore**, indipendente dal set di test:

```csv
gtin,ref,descrizione
07611819268623,413.040S,Vite di bloccaggio
07611819733176,292.720S,Filo guida
```

Le righe sono esempi del formato, non un catalogo completo da caricare senza
controverifica del fornitore. UTF-8, separatore virgola, intestazioni esatte,
GTIN testuale di 14 cifre con zeri iniziali e check digit valido; niente Excel in
notazione scientifica. REF fedele con punti/zeri/suffissi, mai desunto da GTIN o
lotto. `descrizione` può essere vuota, ma la colonna è obbligatoria. Una riga per
GTIN; più GTIN possono puntare allo stesso REF. Duplicati discordanti rifiutati.

```bash
# Installazione SQL nel progetto selezionato, flag archivio sempre false:
psql "$DATABASE_CATALOGO_VERIFICATO" -X -v ON_ERROR_STOP=1 -f sql/articoli_gtin.sql
python scripts/import_articoli_gtin.py /dati/catalogo_fornitore.csv
# Solo quando la validazione è superata; URL e service key via secret manager:
python scripts/import_articoli_gtin.py /dati/catalogo_fornitore.csv --apply
```

`--apply` usa `OCR_CATALOG_SUPABASE_URL` e `OCR_CATALOG_SERVICE_KEY`. Importazione
RPC atomica, idempotente, senza aggiornamenti silenziosi: una corrispondenza già
esistente ma diversa blocca l'import. GTIN e checksum validati anche in Postgres.
Tabella con RLS e soli SELECT/INSERT al server; nessun accesso anon/authenticated.
La service key resta solo sul server. Correzioni del catalogo richiedono revisione
amministrativa esplicita, non un upsert che cambia un'identità esistente.

La lettura app usa ricerca `.eq('gtin', valore)` esatta, con cache per analisi.
La valutazione offline usa lo stesso CSV tramite `--gtin-catalog`; non crea client
Supabase. Nessuna tabella viene popolata dai risultati OCR o dalla ground truth.

Regole: GTIN derivato esclusivamente da GS1 valido; GTIN OCR da solo non basta.
Se il catalogo manca/non risponde o GTIN è sconosciuto: REF vuoto, da verificare.
Se REF stampato e catalogo discordano: REF vuoto, candidato catalogo conservato
separatamente; niente sostituzione automatica. Se OCR non legge il REF: proposta
da catalogo esatto, ancora da verificare per mancato controllo incrociato. Se tutti
i riscontri concordano: metodo `gtin_catalogue_ocr`. Gli ID fisici e le quantità
continuano ad essere gestiti separatamente: stesso GTIN/lotto non prova stesso pezzo.

## 3. Privacy: solo ritagli approvati, niente pagina completa

Eliminate dalla pipeline scarichi le chiamate esterne di localizzazione, audit
della pagina e lettura dell'intestazione. La geometria è locale. Prima di ogni
invio il server richiede approvazione dei ritagli collegata all'hash dei byte del
documento. L'operatore vede ogni ritaglio e seleziona solo quelli senza intestazione,
iniziali, cartella o dati del paziente. Una proposta geometrica errata può essere
esclusa; se mancano etichette si richiedono nuove foto ravvicinate. Il backend
ricontrolla che ogni box selezionato sia una proposta locale del documento attuale:
manifest vecchio, modificato o non approvato => nessuna richiesta al modello.

Una geometria euristica non è una garanzia di anonimizzazione: l'approvazione locale
è obbligatoria proprio per verificare il CONTENUTO del ritaglio. Non selezionare
etichette che abbiano annotazioni identificative del paziente sopra o accanto.
I dati intervento rimangono manuali. Le immagini annotate complete sono solo
anteprime locali, mai inserite nelle richieste esterne.

Per la valutazione live generare i ritagli localmente (fuori dalla cartella foto
usata dal benchmark, per non aggiungere falsi documenti):

```bash
python scripts/prepare_ocr_crops.py --images /dati/foto --out /dati/privacy-review
```

Aprire ogni PNG, rimuovere dal manifest le proposte non sicure, mantenere coordinate
originali e per ciascun documento impostare `approved: true` e
`labels_only_confirmed: true` SOLO dopo il controllo. Non copiare i box della
verità nel manifest: sarebbero un aiuto al lettore che invalida il benchmark.
La UI esegue lo stesso controllo con checkbox individuali e conferma generale.

Il test `test_external_payload_contains_no_header_pixels_or_header_calls` cattura
ogni richiesta effettiva al client, decodifica tutte le immagini e verifica che
nessun pixel dell'intestazione sintetica raggiunga il modello. Altri test
verificano hash errato, box nell'intestazione e mancata approvazione: zero chiamate.
È un test del confine di trasporto, non una prova che ogni localizzatore individui
sempre correttamente le etichette senza verifica umana.

## 4. Valutazione locale e comando live

```bash
python evaluate_ocr.py --images /dati/foto --truth /dati/ground_truth.csv \
 --annotations /dati/annotations.json --gtin-catalog /dati/catalogo_fornitore.csv \
 --mode local --out /dati/report-local-v15

# OPENAI_API_KEY configurata nell'ambiente, mai come argomento o nel file di log.
python scripts/run_ocr_live.py --images /dati/foto --truth /dati/ground_truth.csv \
 --annotations /dati/annotations.json --gtin-catalog /dati/catalogo_fornitore.csv \
 --privacy-manifest /dati/privacy-review/privacy_manifest.json \
 --model gpt-4.1 --repeats 3 --compare /dati/report-local-v15/summary.json \
 --out /dati/report-live-v15
```

Il wrapper esegue la pipeline reale senza scritture Supabase, disabilita i log di
trasporto dettagliati, legge la chiave esclusivamente dall'ambiente, verifica e
filtra log/output. Se rileva la chiave, la rimuove e fallisce il controllo: nessuna
accettazione. Il test usa una chiave fittizia, senza inviare alcuna richiesta live.
Non eseguire con tracing shell `set -x`, proxy che registrano Authorization o log
esterni al processo: il wrapper non può controllare l'infrastruttura del chiamante.
Gli output possono comunque contenere dati clinici residui: mantenerli privati.

Restano valide le soglie di PR39 e la checklist staging/retention. Il solo catalogo
non abilita l'archivio. Nuove versioni pipeline richiedono nuova valutazione.
