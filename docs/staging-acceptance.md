# Collaudo Scarico Sala AI — PR #41 (bozza)

## Stato e condizioni di ingresso

La pagina Streamlit operativa usata finora è produzione: non usarla per inserire dati di collaudo. Non è disponibile un URL staging ospitato verificato. Il progetto Supabase operativo `foawqtscqtwhpkbfbibj` non è uno staging, e la sua branch predefinita `main` non costituisce un ambiente separato. Non è stata eseguita alcuna scrittura nel progetto operativo durante questa verifica.

Il catalogo è stato verificato nello staging **locale isolato PostgreSQL 17**: 29.862 righe. Non è un import nella pagina pubblica. Lo staging Supabase ospitato non è disponibile: prima del collaudo occorrono un progetto separato e una pagina collegata esclusivamente a quel progetto. Non importare il catalogo nel progetto operativo, nemmeno se vuoto.

Predisporre il progetto staging senza copiare utenti, interventi, giacenze o documenti reali. Installare lo schema/RPC aggiornati, importare il catalogo con l'importer staging e poi ripetere l'import per verificarne l'idempotenza. Il pacchetto completo deve dare 29.862 nuove righe al primo passaggio, zero nuove/aggiornate al secondo; conflitti GTIN/REF devono fermare l'intero import. Categorie mancanti restano NULL, senza filtri o categorie inventate.

Configurare nella sola pagina staging:

- `ORTHOFLOW_ENVIRONMENT=staging`;
- `ORTHOFLOW_STAGING_PROJECT_REF` uguale alla reference del progetto separato;
- URL e credenziali appartenenti esclusivamente allo staging;
- marcatore `orthoflow_environment.environment=staging` nel database separato;
- archivio OCR disattivato.

La pagina verifica reference, HTTPS e marcatore DB; se non corrispondono, si ferma prima dei moduli di inserimento. Il progetto operativo noto non può essere dichiarato staging. Questa verifica non certifica da sola l'assenza di copie di dati reali: lo staging deve essere predisposto vuoto e popolato con soli dati sintetici, oltre al catalogo prodotti autorizzato.

## Prove per l'operatore

Eseguire in ordine; per casi indipendenti usare una cartella sintetica diversa (`TEST-OCR-001`, `TEST-OCR-002`, ...). Le cartelle non devono corrispondere a pazienti. Annotare ID intervento e saldi iniziali/finali. Non registrare il PDF clinico originale: per le prove con salvataggio usare una copia anonimizzata oppure etichette e intestazione sintetiche.

| Passo | Azione | Risultato atteso |
|---|---|---|
| 1 | Aprire l'URL staging fornito dal deployment. | Banner **STAGING verificato**, reference diversa dal progetto operativo. Se manca o compare PRODUZIONE, fermarsi. |
| 2 | Controllare configurazione DB e magazzino sintetico `TEST-OCR`. | Nessun collegamento al DB operativo; nessuna giacenza reale. Annotare il saldo del magazzino operativo con sola lettura per confronto finale. |
| 3 | Verificare `articoli_gtin` nello staging ospitato. | Catalogo importato prima delle prove; conteggi e report coerenti, seconda esecuzione senza modifiche. |
| 4 | Caricare il campione anonimizzato con sette etichette. | Sette righe da quantità 1; i quattro REF uguali con lotto diverso restano quattro righe. Nessuna regione privata o intestazione inviata/archiviata. |
| 5 | Usare una riga con GTIN assente/non decodificato/non censito, REF/lotto/scadenza/quantità validi. | GTIN non modificabile e nessun blocco. Solo avviso morbido sul confronto col catalogo. Il GTIN non va cercato dall'operatore. |
| 6 | Correggere REF, lotto e scadenza di una riga, quantità da 1 a 2. | Valori mantenuti dopo rerun; log con prima/dopo, utente, timestamp e metodo manuale. Quantità totale aggiornata. |
| 7 | Aggiungere una riga nella tabella o nel modulo manuale, poi eliminarla. | Conteggio precompilato aumenta di 1 e poi diminuisce di 1; entrambe le operazioni restano nel log. Nessuna foto intera creata come ritaglio. |
| 8 | Svuotare prima REF, poi lotto, poi scadenza; provare quantità 0, negativa e 1,5. | Solo la riga interessata è rossa; messaggio con REF+lotto e campo errato. Nessun intervento o movimento creato finché non viene corretta/eliminata/esclusa. |
| 9 | Inserire una data impossibile, ad esempio 30 febbraio. | Rifiuto della riga. Dopo correzione la data viene trasmessa al server nel formato AAAA-MM-GG. |
| 10 | Modificare il conteggio dichiarato rispetto alle righe incluse. | Avviso con differenza numerica; nessun blocco aggiuntivo. La differenza viene conservata nell'audit. |
| 11 | Inserire due etichette fisiche con stesso REF e lotto. | Quantità aggregata 2. La stessa immagine caricata due volte non viene contata due volte; per foto diverse confrontare ed escludere la ripetizione dello stesso pezzo. |
| 12 | Spuntare l'unica conferma e salvare in `TEST-OCR`, con cartella `TEST-OCR-001`. | Un intervento, quantità esatte, un solo insieme di movimenti e audit delle correzioni. Quantità 2 è accettata anche su una riga manuale. |
| 13 | Fare doppio clic o inviare due richieste simultanee identiche. | Un solo intervento e un solo scarico. La seconda risposta restituisce l'ID già salvato. |
| 14 | Simulare un timeout **dopo** il commit e riprovare senza modificare i dati. | Stesso UUID di richiesta e stesso ID intervento; nessun secondo movimento, anomalia o audit. Non viene dichiarato falsamente un rollback certo dopo un timeout. |
| 15 | Ricaricare/rianalizzare e tentare un nuovo invio con stessa struttura, cartella e data. | Messaggio «Scarico già registrato» con ID precedente, nessuna seconda registrazione. Una nuova cartella identifica un nuovo intervento. |
| 16 | Senza cartella, reinviare lo stesso documento originale. | Ripetizione bloccata dall'identità del documento. Se mancano sia cartella sia documento identificabile, il server richiede la cartella prima del salvataggio. |
| 17 | Reinviare lo stesso UUID dopo aver cambiato i dati. | Rifiuto «Richiesta già usata con dati diversi»; non viene sovrascritto né ripetuto l'intervento precedente. |
| 18 | Creare una discrepanza di giacenza/lotto/scadenza sul solo magazzino sintetico. | Intervento e anomalia salvati; nessuno scarico da giacenza incompatibile o insufficiente. Un retry non duplica l'anomalia. |
| 19 | Controllare il registro dopo il salvataggio e dopo un retry. | Valori originali/corretti e autore presenti nell'audit dell'intervento; nessun audit duplicato. Nessun originale caricato nell'archivio OCR. |
| 20 | Verificare nuovamente i saldi operativi e le impostazioni archivio. | Magazzini reali invariati; archivio ancora OFF. Nessun merge/deployment in produzione. |

## Prove tecniche indipendenti dalla pagina

La pagina usa l’endpoint dedicato `crea_intervento_scarico_ai_verificato_v2`, che forza il contratto rigoroso anche se il client dichiara una versione precedente. La RPC valida i campi anche se il client altera sia righe sia manifesto: REF obbligatorio con formato ammesso, lotto obbligatorio e massimo 20 caratteri senza controlli, scadenza ISO esistente nel calendario, quantità finita/intera/positiva. Il prefisso `manual:` non esenta dai controlli. Il catalogo/GTIN non è una condizione di salvataggio.

Il contratto v2 richiede un UUID di richiesta. Database e scarico sono nella stessa transazione: UUID e risposta vengono salvati solo insieme agli effetti dell'intervento. Un errore annulla tutto e non consuma la chiave. Lock transazionali e vincoli univoci serializzano richieste concorrenti per UUID, cartella/struttura/data e documento originale. La cartella non è globalmente unica: stessa cartella in altra struttura o data non viene automaticamente considerata lo stesso intervento; il riutilizzo dello stesso documento resta comunque bloccato. Nessuna deroga automatica per un secondo intervento legittimo sulla stessa cartella/data: serve revisione della registrazione esistente.

La protezione nuova si applica al flusso v2 di questa PR e alle registrazioni eseguite dopo la sua installazione. Non modifica o ripara gli interventi storici, ma ferma una nuova registrazione con struttura/cartella/data già presenti anche prima della sua installazione. Non estende automaticamente le garanzie di concorrenza ad altre RPC legacy. Il confronto su documento usa l'originale identificato: trasformazioni/ricodifiche possono cambiare l'hash, perciò la cartella clinica è la protezione stabile dopo reimportazioni differenti. Le operazioni accessorie sui kit non vengono ripetute automaticamente quando il server restituisce un replay; eventuali completamenti vanno riconciliati separatamente.

Test inclusi:

- `tests/discharge_idempotency.sql`: doppio invio, retry dopo risposta persa, nuova richiesta su stessa cartella, documento ripetuto, riuso UUID con dati differenti;
- `tests/discharge_concurrency.sh`: due connessioni PostgreSQL reali simultanee, un solo intervento/movimento e giacenza scalata una volta (solo database CI locale fisso);
- `tests/server_review_validation.sql`: valori invalidi anche su riga manuale e manifesto concorde, nessun effetto parziale;
- `tests/simple_review.sql`: GTIN `nan` non blocca una riga valida; quantità manuale, audit e discordanza conteggio;
- test pagina: stesso UUID conservato dopo timeout, conferma unica, modifica/aggiunta/cancellazione;
- `tests/test_staging_identity.py`: produzione non etichettabile staging, ref/marker/HTTPS obbligatori.

Queste sono prove automatiche isolate, non un collaudo già avvenuto sullo staging ospitato. La PR resta in bozza e l'archivio OFF. Il collaudo ospitato è bloccato finché non è disponibile un progetto staging separato con relativo URL della pagina; la pubblicazione in produzione richiede conferma esplicita successiva.
