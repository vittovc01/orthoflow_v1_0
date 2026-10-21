# Mini: orientamento e confronto delle etichette

Il campione Pineta Grande ha 12 adesivi fisici; la schermata ne proponeva 19. Il vecchio matching sommava osservazioni non abbinate quando mini forniva posizioni incoerenti e campi incompleti. Non è una dimostrazione di accuratezza equivalente ad Astra.

Restano due richieste mini della pagina intera, senza fallback costosi. La seconda riceve la pagina ruotata di 90 gradi; coordinate e rotazione tornano nel sistema originale prima del confronto. Prompt esplicito su LOT, misure e data stampata.

La lettura più completa è la base; le occorrenze dello stesso REF sono abbinate una a una, preservando quantità e lotti distinti. Campi disponibili in una sola lettura restano proposte non verificate. Discordanze effettive restano vuote, con entrambe le evidenze. Osservazioni aggiuntive ambigue restano recuperabili e non aumentano automaticamente il conteggio.

Il decoder locale legge la pagina intera a lato massimo 2000px, senza salvare o trasmettere nuovi pixel. I DataMatrix hanno coordinate e sono associati soltanto a un unico contorno AI che ne include il centro. Payload contrastanti restano conflitti; nessuna sostituzione silenziosa dei valori OCR. La lettura locale del campione ha decodificato sei payload distinti; ciò non prova che i loro contorni AI siano abbinabili. Nessun dato clinico è incluso nelle fixture o nel report.

La versione v19 richiede rianalisi delle revisioni precedenti prima di scaricare materiale: i vecchi 19 risultati non vengono corretti automaticamente. Non è stata eseguita una chiamata mini reale con questa modifica; orientamento, conteggio e associazione sono coperti da test offline, ma la precisione sul campione richiede collaudo reale. Nessun movimento di magazzino effettuato.
