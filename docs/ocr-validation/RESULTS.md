# Esito iniziale V14 — 15 ottobre 2026

> Risultati storici. Il nuovo confronto è in [V15](../ocr-validation-v15/RESULTS.md).

**ERRORI SILENZIOSI: 0 osservati nei due esperimenti locali. LIVE: NON MISURATI.**
**ESITO COMPLESSIVO: BLOCKED. Archivio non attivato.**

| Esperimento | Etichette vere / abbinate | Regioni extra | REF esatti | Lotti esatti | Scadenze esatte | Quantità non risolte |
|---|---:|---:|---:|---:|---:|---:|
| Foto ospedaliera completa fornita dall'utente | 7 / 7 | 0 | 2 / 7 | 0 / 7 | 0 / 7 | 7 gruppi |
| 16 ritagli reali di etichette già nel repository | 16 / 13 | 4 | 0 / 16 | 13 / 16 | 13 / 16 | 16 gruppi |
| Modello di visione live | non eseguito | — | — | — | — | — |

Le colonne campi errati comprendono i campi assenti, non solo trascrizioni
sbagliate. Nella foto completa sono segnalati 6/7 REF e tutti i lotti/scadenze;
nei ritagli 16/16 REF e 3/16 lotti/scadenze (etichette non abbinate).
Gli errori silenziosi non emergono perché la lettura locale si astiene spesso:
non significa che il sistema sia pronto. Accuratezza campi 9,52% sulla foto
completa e 54,17% sui ritagli; revisione richiesta rispettivamente 95,24% e 45,83%.

La foto completa è rimasta privata e non è stata aggiunta al repository. I suoi
report diagnostici sono nel pacchetto consegnato, con verità trascritta visivamente
ma NON controverificata da un secondo operatore. Sul bordo destro due etichette
sono tagliate: entrambe segnalate. Questo non copre ancora tutte le condizioni.
I 16 ritagli provengono da un solo documento storico: non sono 16 scarichi
indipendenti e non misurano la ricerca di etichette in una distinta completa.
`case_id` separati nel loro esempio servono solo a leggerli singolarmente.

## Cause osservate e correzioni

1. Foto completa: la geometria locale trova le 7 etichette; ZXing non recupera
   payload affidabili in questa immagine e il baseline locale non dispone del
   ripiego di visione per lotto/scadenza. I campi restano vuoti e segnalati. Serve
   il confronto live prima di giudicare la pipeline completa.
2. Ritagli: la localizzazione locale può dividere un ritaglio già isolato o
   produrre regioni troppo strette (13 match, 3 mancanti, 4 extra); in questi
   ritagli il REF locale non supera i controlli letterali. Non sono stati allargati
   i box usando la verità per migliorare artificialmente il risultato.
3. Individuato e corretto un difetto nel parser TSV Tesseract: le virgolette OCR
   erano interpretate come quoting CSV e potevano assorbire righe successive.
   Ora `QUOTE_NONE` preserva i token; regressione dedicata. Questa correzione da
   sola non porta i due esperimenti alla soglia.
4. Identità fra foto: stesso REF/lotto non è un identificatore univoco del pezzo.
   File byte-identici non vengono ricontati. Foto diverse con identità di lotto
   uguale richiedono una decisione esplicita distinta/duplicato: nessuna quantità
   sicura viene proposta finché l'ambiguità non è risolta. Test dedicati coprono
   sia il pezzo ripetuto sia due veri pezzi dello stesso lotto.
5. Aggiunti avvisi misurati per buio, sfocatura, possibili riflessi, inclinazione,
   contatto/sovrapposizione fra box. Sono euristiche da validare su foto reali,
   non rilevatori completi garantiti.

## Modello live e sicurezza

Il comando live è stato invocato, ma `OPENAI_API_KEY` non è configurata in questo
ambiente: uscita 4, `NOT_RUN`, metriche `null`, mai riportate come zero. Mancano
anche alcune dipendenze complete dell'app nel runtime locale; il comando fornito
va eseguito nell'ambiente dell'app o dopo l'installazione dei requisiti.
Il confronto numerico locale/live non è quindi disponibile.

Soglie, comandi e formato annotazioni in `README.md`. Report locali dei ritagli
in `local-crops/`; prova live non eseguita in `live-crops/`. I test automatici
verificano scoring e blocchi; non sostituiscono l'esperimento live.

SQL di staging, probe A/B Storage/URL firmati, inventario retention e preflight
sono pronti. Nessun progetto remoto di staging è stato modificato/testato e
nessuna verifica RLS remota viene dichiarata superata. Restano da chiudere la
controverifica della verità, il set completo, le prove live e la checklist
sicurezza/privacy (inclusi minimizzazione prima del modello e cancellazione
controllata dell'archivio append-only).
