# Riconoscimento indipendente dall'orientamento del modulo

Documento storico della v14. Dalla v15 la lettura primaria usa la pagina intera:
vedere `whole-page-reading.md`. Le garanzie di esclusione dell'intestazione dalle
chiamate esterne descritte qui si riferiscono esclusivamente alla vecchia v14.

La pipeline v14 applica il filtro privacy nell'orientamento di lettura dei prodotti,
ricavato localmente dai DataMatrix validi (oppure dagli ancoraggi fisici). Le coordinate
sono riportate alla pagina originale: nessun dato clinico va ai servizi OCR esterni.

Un DataMatrix decodificabile non garantisce che il vecchio rilevatore morfologico
ritrovi il suo contorno. Un secondo ancoraggio usa quindi i loghi stampati DePuy Synthes
insieme al testo REF puntato e calibra le dimensioni sui simboli presenti nella foto.
Mantiene gli ancoraggi già validi e aggiunge solo quelli non sovrapposti. Non usa
struttura, cartella clinica, REF o lotto attesi, coordinate fisse del modulo o un numero
prefissato di etichette. La famiglia di etichette con barcode lineari mantiene il suo
rilevatore distinto. Un modulo nuovo non richiede una nuova tabella di coordinate.

La rotazione della pagina è separata dall'inclinazione del singolo adesivo. Gli assi del
simbolo orientano il rettangolo completo prima del ritaglio; una rotazione residua
misurata sul DataMatrix raddrizza il prodotto prima delle letture indipendenti.
L'OCR letterale locale interpreta i TSV senza trattare le virgolette come delimitatori:
un carattere riconosciuto come virgolette non può assorbire righe successive.

Un controllo indipendente confronta inoltre le posizioni dei DataMatrix decodificati
con i ritagli: eventuali prodotti fuori dai ritagli generano un avviso di lettura
incompleta. Due simboli con lo stesso GTIN restano due posizioni fisiche.

I campi restano letterali: nessuna sostituzione 5/S, nessuna aggiunta di suffissi o
ricostruzione dal nome del prodotto. Lotti e scadenze vengono confrontati col GS1.
Le discordanze restano esplicite e richiedono verifica. GTIN tecnico e assenza dal
catalogo non bloccano la conferma. L'archivio prodotto della PR #42 resta attivo.

## Verifica riproducibile

```bash
python -m pytest -q tests/test_product_anchors.py tests/test_region_privacy.py tests/test_label_geometry.py tests/test_literal_evidence_conflicts.py
python scripts/evaluate_ocr.py
# Qualsiasi nuovo documento, con verità di riferimento separata:
python scripts/evaluate_ocr.py --input /percorso/documento.pdf --truth-json /percorso/boxes.json --read-fields
```

`boxes.json` è un array di rettangoli `[sinistra,alto,destra,basso]` in coordinate
0..1000. Il rapporto distingue recupero delle regioni, lettura locale letterale dei
REF e decodifica di lotto/scadenza. Non attribuisce al modello AI risultati che non
sono stati ottenuti da un'esecuzione live. Il test sintetico colloca sette etichette
esistenti su un modulo diverso e lo ruota di 0/90/180/270 gradi, controllando recupero,
assenza di regioni extra, copertura dei prodotti e oscuramento dell'intestazione.

Il documento operativo usato per la diagnosi e le sue verità di riferimento restano
locali e non vengono pubblicati nel repository. Riconoscimento e salvataggio sono
separati: nessun movimento di magazzino è necessario per valutare una lettura.
