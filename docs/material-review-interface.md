# Revisione rapida dei materiali

Il risultato mostra una lista modificabile con REF, lotto, scadenza, descrizione,
quantità ed esclusione della riga. Le righe fisiche restano separate per preservare
il collegamento alle etichette e la traccia delle correzioni. La registrazione
continua ad aggregare le quantità con le regole esistenti.

Excel e CSV esportano la lista corrente dopo le modifiche, escludendo le righe
selezionate come escluse e senza GTIN, dati clinici, immagini o metadati tecnici.
Lotto e REF sono celle testuali in Excel. Il CSV usa separatore punto e virgola,
UTF-8 con BOM; i testi che potrebbero essere formule vengono neutralizzati.

I controlli GTIN/catalogo e i riscontri delle singole etichette sono disponibili
solo aprendo i dettagli tecnici e attivandone la visualizzazione. Gli errori sui
campi obbligatori restano visibili nella lista. Il modulo alternativo per aggiungere
o correggere materiale è chiuso di default, sotto la tabella. La conferma globale
e la validazione server, il registro correzioni e le protezioni di idempotenza
restano invariati. La sola archiviazione è un'opzione secondaria chiusa.

## Tempi

- Stessi modello, risoluzione, prompt e due letture API sequenziali: nessuna riduzione
  del controllo incrociato e nessun aumento di richieste concorrenti al provider.
- La pagina viene codificata in PNG/base64 una sola volta per entrambe le letture.
- Dopo la prima lettura riuscita, un solo worker locale prepara i riscontri prodotto
  durante la seconda lettura; non decide quali pixel riceve il modello. Prima di
  usare i ritagli si attende il risultato del filtro privacy originale.
- Il catalogo autorevole viene riutilizzato nella sessione per la stessa revisione;
  una nuova analisi lo ricarica. Nessuna copia globale condivisa tra utenti.
- Dopo la lettura l'anteprima originale viene costruita solo su richiesta, evitando
  di rigenerare PDF/immagini a ogni modifica di cella.
- La pagina riporta la durata effettiva dell'analisi, inclusa la lettura del catalogo.

I test verificano sovrapposizione locale/API con eventi di sincronizzazione,
unicità della codifica, campi invariati, export aggiornato e una sola lettura del
catalogo anche dopo modifiche. Non costituiscono una misura di latenza del servizio
AI reale. Il guadagno reale dipende da foto, riscontri locali e tempo del provider;
non viene promesso un numero fisso di secondi.

Nessuna modifica a schema, magazzino, fatturazione API o impostazioni dell'archivio.
