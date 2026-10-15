# Valutazione offline riproducibile e catalogo completo per staging

Archivio OCR disattivato. Nessun modello esterno invocato. Nessuna scrittura su Supabase.

## Risultati reali

Prima e dopo sono nuove esecuzioni di evaluate_ocr.py nello STESSO ambiente,
con lo stesso hash pipeline e dataset. Prima: senza catalogo. Dopo: CSV ufficiale
J&J completo, estratto dal file scaricato da Customer Connect (data interna
20/06/2024). Non è un confronto fra decoder V14 e V15.

| Campione | Fase | DataMatrix | REF corretti | Lotti | Scadenze | Errori silenziosi | REF da verificare | Etichette da verificare |
|---|---|---|---|---|---|---|---|---|
| Foto completa | Prima | 5/7 | 0/7 | 5/7 | 5/7 | 0 | 7/7 | 7/7 |
| Foto completa | Dopo | 5/7 | 5/7 | 5/7 | 5/7 | 0 | 6/7 | 7/7 |
| Ritagli | Prima | 16/16 | 0/16 | 16/16 | 16/16 | 0 | 16/16 | 16/16 |
| Ritagli | Dopo | 16/16 | 16/16 | 16/16 | 16/16 | 0 | 16/16 | 16/16 |

REF assenti prima del catalogo sono conteggiati come non corretti, non come
trascrizioni errate. I valori da catalogo senza un REF OCR indipendente restano
segnalati. Mancano inoltre descrizioni verificate; riflessi/bordi determinano
ulteriori richieste di controllo. Quindi REF corretto non significa etichetta sicura.
Sulla foto completa restano 2 DataMatrix non decodificati e tutte le quantità
non risolte (7). Nei ritagli le quantità non risolte passano da 16 a 0;
sono casi separati, non una prova di deduplicazione tra foto dello stesso scarico.
Le annotazioni richiedono controverifica indipendente; campione troppo piccolo,
nessun live, soglia di accettazione NON raggiunta.

Ambiente eseguito: Python 3.12, OpenCV headless 4.11.0.86, zxing-cpp 2.3.0,
Pillow 11.3.0, PyMuPDF 1.26.4, NumPy 2.2.6, Tesseract 5.3.4.
69 test Python passati, inclusi esclusione intestazioni e discordanza REF.
Migrazione e test SQL passati su PostgreSQL WASM locale (PGlite), inclusi accessi
negati anon/authenticated e rollback dei conflitti. Import locale completo:
49.140 nuove, 0 aggiornate; seconda esecuzione 0 nuove, 0 aggiornate,
49.140 invariate. Questo NON è un import su staging Supabase remoto.
Docker non è disponibile nel runner locale. Successivamente la CI GitHub
38811508063 ha completato con successo build del container, 23 test Python
nel container e test SQL su PostgreSQL 17.6 nativo. Nel container (Tesseract
5.3.0), la valutazione senza catalogo sui 16 ritagli conferma 16/16 lotti e
scadenze, 0 REF risolti e 0 errori silenziosi. Il confronto completo prima/dopo
qui riportato rimane quello dell’ambiente locale dichiarato sopra. Il Dockerfile usa
un'immagine base con digest fissato e pacchetti Debian da snapshot fisso:
la versione Tesseract del container può differire da questa esecuzione locale.
I futuri confronti vanno eseguiti entrambi nello stesso container.

## Container e comandi

Dalla radice del repository:

```bash
docker build --platform linux/amd64 -f docker/ocr/Dockerfile -t orthoflow-ocr .
# Prima: nessun catalogo, nessuna rete e nessun secret.
docker run --rm --network none -v "$PWD/reports:/reports" orthoflow-ocr \
 --mode local --images tests/fixtures/santa_lucia \
 --truth tests/evaluation/ground_truth.csv --annotations tests/evaluation/annotations.json \
 --out /reports/prima
# Dopo: catalogo ufficiale montato in sola lettura.
docker run --rm --network none -v "$PWD/reports:/reports" \
 -v /percorso/catalogo_completo.csv:/data/catalogo.csv:ro orthoflow-ocr \
 --mode local --images tests/fixtures/santa_lucia \
 --truth tests/evaluation/ground_truth.csv --annotations tests/evaluation/annotations.json \
 --gtin-catalog /data/catalogo.csv --out /reports/dopo
```

Exit 2 con status COMPLETED indica gate BLOCKED; dipendenze mancanti producono
NOT_RUN, mai zero errori come se la valutazione fosse riuscita. La CI separa
esecuzione corretta, zero errori silenziosi e approvazione per produzione.

## Catalogo completo e staging

Nessun filtro di categoria: entrambi i campi GTIN del workbook, tutte le franchise,
compresi articoli non più attivi. Fonte conserva nome file, versione interna,
tipo di GTIN e stato. Categoria contiene Franchise / Divisione / Gruppo prodotti.

Validazione reale: 49.140 GTIN distinti validi, 30 occorrenze duplicate consolidate,
2 righe scartate (GTIN 10705034388235 e 10705034388249: checksum non valido),
nessun GTIN con REF discordanti. Tutte le categorie sono elaborate; ciò non
significa che tutti gli articoli del file abbiano un GTIN compilato o valido.
Le descrizioni discordanti sono anch'esse bloccanti, mai scelte arbitrariamente.
I file commerciali completi non sono pubblicati nel repository.

```bash
python scripts/import_catalog_staging.py /dati/MDD-PRODUCT-CATALOG.xls --out /dati/import
# Migrazione generata con Supabase CLI; solo connessione staging verificata.
PGOPTIONS='-c orthoflow.environment=staging' psql "$OCR_STAGING_DATABASE_URL" \
 -X -v ON_ERROR_STOP=1 -f sql/articoli_gtin_staging_v2.sql
# URL, project ref e service key dello staging forniti dal secret manager.
python scripts/import_catalog_staging.py /dati/MDD-PRODUCT-CATALOG.xls --out /dati/import --apply
```

Variabili: OCR_STAGING_SUPABASE_URL, OCR_STAGING_PROJECT_REF,
OCR_STAGING_SERVICE_KEY. Il progetto produzione noto è vietato esplicitamente;
URL e ref devono coincidere. La RPC richiede anche il marker staging creato dalla
migrazione. Non applicare la migrazione su produzione. È disponibile anche la
stessa migrazione in supabase/migrations, generata con migration new.

Import atomico: chiave GTIN, più GTIN per REF; nessuna modifica di REF per un GTIN
già presente. Conflitti interni o con database bloccano l'intera transazione.
Descrizione/categoria/fonte possono aggiornarsi; data_import cambia solo per
righe nuove o modificate. Un import identico non modifica dati né timestamp.
Report: nuove, aggiornate, invariate, scartate e duplicati. Nel dry-run le tre
metriche dipendenti dal database sono null, perché NON è avvenuto un import.
RLS attiva, accesso solo server; test SQL coprono idempotenza, aggiornamenti,
conflitti e accesso negato ad authenticated.

Non è stato identificato un progetto staging: disponibile soltanto il progetto
app foawqtscqtwhpkbfbibj. Import remoto e test RLS su staging restano da eseguire.

## GTIN mancanti e discordanti

Un GTIN valido sconosciuto non produce un REF. La revisione offre il download
GTIN mancanti; ogni valutazione genera gtin_mancanti.csv. Il file contiene solo
GTIN e numero di occorrenze, senza pazienti, lotti, immagini o nomi file.
L'elenco resta nello stato della revisione e nei report locali, senza scritture
in background. Le occorrenze contano letture, non quantità fisiche confermate.
Catalogo indisponibile è distinto da GTIN assente: un guasto non genera falsi
GTIN mancanti. REF OCR discordante: campo vuoto, candidato conservato per
revisione, nessuna correzione automatica.

## Nuove foto ad alta risoluzione

```bash
docker run --rm --network none --entrypoint python \
 -v /dati/nuove-foto:/data:ro -v "$PWD/reports:/reports" orthoflow-ocr \
 scripts/benchmark_datamatrix.py --images /data/foto --truth /data/ground_truth.csv \
 --annotations /data/annotations.json --scales 1,.75,.5,.375,.25 \
 --out /reports/risoluzione.csv
```

CSV: dimensioni native ed effettive, scala, etichette attese, regioni, payload,
lotto/scadenza corretti e tasso. Denominatore dalla verità manuale; upscaling
escluso. Sono incluse le perdite di localizzazione. Sul file attuale:
900×1600: 5/7 (71,4%); 675×1200: 1/7 (14,3%); 450×800: 0/7.
Nessuna risoluzione minima universale dimostrata da questo campione.
