# OrthoFlow WMS 8.0

Modulo riservato ai ruoli **Admin** e **Magazzino**. Gli agenti continuano a utilizzare Scarico sala e non possono vedere ubicazioni, quantità, scaffali o giacenze.

## Flusso operativo

1. Creare le ubicazioni con formato `MAG1-ZONA-SCAFFALE-RIPIANO-POSTAZIONE`.
2. Scaricare i QR in ZIP e stamparli.
3. Applicare un QR alla testata dello scaffale e uno alle postazioni finali realmente utilizzate.
4. Importare DDT/giacenze nel flusso OrthoFlow esistente.
5. Aprire **WMS → Posizionamento** per distribuire fisicamente Codice + Lotto nelle ubicazioni.
6. Usare **Scanner** per leggere QR OrthoFlow e codici GS1/DataMatrix Johnson.
7. Usare **Scadenze** per il giro FEFO con scaffale, ripiano e postazione.

## Etichette

- testata scaffale: QR minimo 40×40 mm;
- ripiano/postazione: QR minimo 30×30 mm;
- stampare sempre anche il codice ubicazione in chiaro;
- non aggiungere QR sulle confezioni Johnson: usare il DataMatrix o codice a barre originale;
- un QR dedicato è utile per i set riutilizzabili gestiti come unità logistica.

## Codici Johnson / GS1

Il primo utilizzo di un GTIN/DataMatrix può richiedere l'associazione al codice articolo Johnson. L'associazione viene salvata nella tabella `codici_prodotto_scan` e riutilizzata nelle scansioni successive.

I dati estratti automaticamente (GTIN, lotto e scadenza) devono essere confermati dall'operatore durante la fase pilota.

## Sicurezza

Le tabelle WMS e le funzioni RPC sono accessibili tramite la service key dell'app. Non esporre mai `SUPABASE_SERVICE_KEY` nel repository o nel browser.
