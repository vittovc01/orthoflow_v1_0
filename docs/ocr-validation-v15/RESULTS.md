# Confronto prima/dopo — 15 ottobre 2026

**Errori silenziosi osservati: 0 prima e 0 dopo nei due set locali.**
**Esito: BLOCKED. `OCR_REVIEW_ARCHIVE_ENABLED` resta false.**
Nessuna chiamata al modello live eseguita; il comando è preparato per l'ambiente
utente. La verità delle foto non è ancora controverificata da un secondo operatore.

## Valutatore reale locale

| Set / metrica | PR39 prima | V15 dopo |
|---|---:|---:|
| Foto completa, etichette abbinate | 7/7 | 7/7 |
| Foto completa, regioni extra | 0 | 0 |
| Foto completa, lotti esatti | 0/7 | 5/7 |
| Foto completa, scadenze esatte | 0/7 | 5/7 |
| Foto completa, REF esatti proposti | 2/7 | 0/7, catalogo non fornito |
| 16 ritagli, etichette abbinate | 13/16 | 16/16 |
| 16 ritagli, regioni extra | 4 | 0 |
| 16 ritagli, lotti esatti | 13/16 | 16/16 |
| 16 ritagli, scadenze esatte | 13/16 | 16/16 |
| 16 ritagli, REF esatti proposti | 0/16 | 0/16, catalogo non fornito |
| Errori silenziosi nei due set | 0 | 0 |
| Quantità aggregate | non risolte | non risolte: REF da verificare |

Il numero di REF non migliora artificialmente: con la nuova regola GTIN→REF,
senza catalogo ufficiale il sistema non accetta più il REF dall'OCR come identità
primaria. Tutti i REF restano da verificare. Non è stata creata una tabella di
corrispondenze dalle annotazioni del benchmark, perché falserebbe la valutazione.
La tabella Supabase è stata creata e verificata (RLS attivo, accessi client negati,
import discordante/checksum/idempotenza testati con rollback; zero righe residue).
Il catalogo vuoto deve essere popolato dal CSV ufficiale del fornitore.

I 16 ritagli provengono da un solo documento storico, diverso dalla foto completa
a 7 etichette. **Non è un confronto controllato della sola dimensione di ritaglio.**
I report hanno fingerprint di immagini/verità/pipeline; CSV originali e nuovi
rimangono separati. Il metodo locale non esegue OCR visivo del modello: il
confronto live resta da fare con catalogo e manifest privacy approvato.

## Causa: separazione geometria/decoder

Per isolare l'effetto del decoder è congelata la funzione di PR39 in
`tests/evaluation/decoder_v14_reference.py`, usata esclusivamente dal benchmark.
Stessi ritagli locali per i due decoder (non box della verità):

| Stessi ROI nativi | Decoder PR39 | Decoder V15 |
|---|---:|---:|
| Sette adesivi della foto completa | 0/7 | 5/7 |
| Sedici foto già ritagliate | 15/16 | 16/16 |

Quindi il precedente 13/16 nel valutatore NON era soltanto un limite ZXing:
alcuni ritagli venivano segmentati nuovamente in regioni troppo strette. La nuova
identificazione di una foto già isolata con un solo GS1 valido elimina questo
errore di geometria. Sul sedicesimo codice la rotazione del sorgente prima della
soglia adattiva e del ricampionamento recupera il payload. Le rotazioni dopo la
sola soglia non erano equivalenti per fase di campionamento e arrotondamenti.

Sulla foto completa i finder misurati occupano circa **24–34 px per lato**. I
ritagli degli adesivi restano quelli della foto originale: ingrandire non crea
nuovi moduli leggibili. Un primo passaggio soglia adattiva/scale recuperava solo
un payload. La ricerca nel SOLO finder, con margini locali 15/35/60% entro i
confini dell'etichetta, e ricampionamento PRIMA della soglia adattiva recuperano
altri quattro payload. Il metodo è generale, senza condizioni sui codici/lotti.
Non usa box della verità o immagini ricostruite. Gli offset di soglia 0/2/7/11,
blocchi 7/11/15/21/31 e scale 1/1.5/2/3/4 hanno un massimo di 200 tentativi per
micro-ROI; ZXing ECC e parser GS1 con FNC1/check digit restano obbligatori.

I cinque lotti recuperati sono `470L068`, `11598P5`, `470L625`, `46993P5`,
`92021P0`; tutte le rispettive scadenze concordano con la verità diagnostica.
I due ancora non decodificati (`332600P` e `131962P`) sono proprio le etichette
tagliate sul bordo destro: restano vuoti e segnalati, entrambe con avviso di bordo.
Servono nuove foto con l'intera etichetta e il codice incluso, non valori dedotti.
Non si può attribuire con certezza tutta la perdita alla compressione: la foto
non conserva necessariamente i metadati di ogni precedente trasformazione.

## Tasso in funzione della risoluzione di partenza

Ricampionamento LANCZOS verso il basso; nessun upscaling presentato come nuovo
originale. Pipeline locale completa, inclusa individuazione dei ritagli.

| Foto completa: dimensioni disponibili | Payload corretti / etichette | Tasso |
|---|---:|---:|
| 900×1600, nativa | 5/7 | 71,4% |
| 675×1200 | 1/7 | 14,3% |
| 450×800 | 0/7 | 0% |
| 338×600 | 0/7 | 0% |
| 225×400 | 0/7 | 0% |

| Singoli adesivi: lato lungo effettivo | Payload corretti / etichette | Tasso |
|---|---:|---:|
| 680–733 px, nativo | 16/16 | 100% |
| 510–550 px, 75% | 16/16 | 100% |
| 340–366 px, 50% | 12/16 | 75% |
| 255–275 px, 37,5% | 0/16 | 0% |
| 170–183 px, 25% | 0/16 | 0% |

**Risoluzione minima universale non determinata.** Il campione indica che la
foto completa 900×1600 è insufficiente per leggere tutti i GS1; non abbiamo il
suo originale più definito per trovare una soglia di successo completo. Il
risultato 510–550 px riguarda UNA etichetta isolata, non un'intera pagina.
Target UI conservativi (2400 px lato lungo pagina, finder >=64 px) sono
provvisori e richiedono nuovi originali reali per validazione, non una garanzia.

## Sicurezza e test

- Matching catalogo esatto, checksum, GTIN ignoto, REF discordanti/assenza OCR:
  regressioni dedicate. Import atomico senza sovrascritture silenziose.
- Richieste modello catturate e immagini decodificate nei test: nessun pixel
  dell'intestazione sintetica inviato; nessuna chiamata di lettura header/pagina.
  Senza approvazione locale, hash corretto e box ammessi: zero chiamate.
- Il controllo umano verifica anche annotazioni identificative accidentalmente
  presenti SUL ritaglio; nessuna euristica sostituisce questa approvazione.
- Log: test con chiave fittizia e simulazione di processo che la emette; valore
  rimosso, log pulito e accettazione bloccata. Nessuna chiave reale usata.
- Test locali principali: 129 superati, inclusi decoder, catalogo, privacy,
  controllo log e preflight; regressione form superata. CI completa collegata
  alla PR verifica anche SQL su PostgreSQL isolato, pagine, container e browser.

L'esito resta bloccato per foto completa insufficiente, catalogo non fornito,
quantità non risolte, campione piccolo e non controverificato, casi limite incompleti
e modello live non eseguito. Rimangono applicabili checklist staging/retention e
soglie di accettazione della PR39. Il nuovo schema GTIN non abilita l'archivio.

## Verifica schema Supabase

`articoli_gtin` creata nel progetto dell'app dopo esito positivo dei test SQL
in CI. Eseguiti anche i test transazionali reali, con rollback dei dati sintetici:
import, idempotenza, conflitto, checksum e accesso autenticato negato. Verifica
finale: 0 righe, RLS true, anon SELECT false, authenticated INSERT false,
service_role SELECT true. Nessun dato catalogo è stato inventato/importato.
L'advisor rileva INFO `rls_enabled_no_policy`, coerente con l'accesso solo server
e con i privilegi client revocati; non va risolto concedendo letture pubbliche.
[Riferimento advisor](https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy).
Il flag archivio e lo schema dell'archivio restano invariati in produzione.
