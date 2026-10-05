# Protezione dati e collaudo prima della pubblicazione

Il piano Supabase resta Free. Nessun abbonamento o servizio di hosting è attivato da queste modifiche.

## Caricamenti

Tutti i caricamenti documentali su Supabase di scarichi, DDT e corrieri passano dalla compressione condivisa. Le copie usate per OCR restano inalterate; la compressione interessa l'archivio. Foto JPEG: qualità 88, piena risoluzione cromatica, nessun ridimensionamento. PNG e firme desktop: compressione senza perdita. PDF: compressione dei flussi e deduplicazione, senza rasterizzazione né perdita di pagine, testo o annotazioni. PDF con campi firma/ByteRange: originali identici. Se il risultato non è più piccolo, si conserva il sorgente; mobile mantiene sempre la sanitizzazione delle immagini. Nessuna garanzia di riduzione fissa, soprattutto per scansioni già compresse. File già archiviati non sono riscritti.

## Spazio e disponibilità

Applicare `sql/cloud_capacity.sql` con un ruolo amministrativo. Solo `service_role` può eseguire la funzione. Il dashboard Controllo di Gestione mostra all'Admin un espandibile con database, file e soglie 80%/95%; una misura fallita è "non disponibile", mai zero. Default quote Free: 500.000.000 byte database, 1.000.000.000 byte Storage. Configurare `CLOUD_DATABASE_LIMIT_BYTES` e `CLOUD_FILE_LIMIT_BYTES` in secrets/env e repository variables quando cambia il piano. Misure indicative, non sostituiscono il conteggio fatturato da Supabase.

`/health` mobile prova anche una lettura Supabase, restituendo 503 quando il backend non risponde, senza dettagli sensibili. Le verifiche GitHub di disponibilità sono predisposte ogni 30 minuti: solo se `MOBILE_PUBLIC_URL`/`DESKTOP_PUBLIC_URL` sono configurati. GitHub schedules possono subire ritardi, non sono un monitor con SLA. Sul Free la verifica può risvegliare il servizio: non elimina i limiti del piano né garantisce disponibilità continua.

## Backup giornaliero cifrato

Il workflow `Protezione cloud OrthoFlow` è predisposto alle 02:17 UTC. **Non è operativo finché non sono configurate credenziali, chiave e variabili di abilitazione.** Non interpreta un job saltato come backup riuscito.

Secrets GitHub richiesti:
- `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`: credenziali server, mai pubblicate nel repository/browser.
- `BACKUP_DATABASE_URL`: connessione PostgreSQL diretta o session pooler (non transaction pooler), password in secret, SSL richiesto.
- `BACKUP_ENCRYPTION_KEY`: chiave casuale di 32 byte codificata base64. Generare localmente e conservarne una copia sicura esterna a GitHub; senza chiave i backup sono irrecuperabili.

Variabili GitHub: `CLOUD_BACKUP_ENABLED=true`, `CLOUD_MONITOR_ENABLED=true`. Prima eseguire manualmente il workflow e verificare un archivio, poi abilitare l'automatismo. Per notifiche di errore usare le notifiche GitHub Actions dell'account, da verificare con un errore simulato.

Il backup contiene schema/dati applicativi `public` (inclusi utenti OrthoFlow), manifest dei bucket e ogni oggetto Storage. Non esporta configurazione provider/secrets, ruoli globali o schema Supabase Auth; se si passa a Supabase Auth, estendere il backup prima dell'uso. Si usa pg_dump 17, compatibile con il progetto attuale. L'inventario deve rimanere identico durante l'export: variazioni/download falliti invalidano l'operazione e richiedono un nuovo tentativo in una finestra tranquilla. AES-256-GCM cifra l'archivio, hash SHA-256 e prova di decifratura verificano ogni file. Solo `.enc` è caricato fra gli artifact GitHub, con conservazione 30 giorni. I costi/limiti degli artifact e del traffico Supabase devono essere controllati: non è una promessa di backup illimitato gratuito. Copiare periodicamente un archivio verificato anche su un secondo supporto protetto per conservazione a lungo termine.

## Ripristino e prove

`python scripts/cloud_backup.py --decrypt backup.enc --output verified.zip` decifra e verifica; non modifica alcun database. Usare un dispositivo affidabile e proteggere la ZIP in chiaro. Manifest: mapping bucket/percorso originale → entry numerica, tipo/metadata, dimensione e hash. Ripristinare gli oggetti tramite Storage API in un progetto di prova mantenendo percorsi e bucket privati. Non scrivere direttamente su storage.objects.

Ripristinare database.dump prima in un progetto Supabase di prova compatibile: predisporre estensioni, ruoli e schemi richiesti, verificare pg_restore senza owner/ACL, riapplicare GRANT/RLS dalle migrazioni del repository perché l'archivio non esporta ACL. Verificare quantità, prezzi, interventi, relazioni e accessi; poi documentare tempi e risultato. Nessun ripristino automatico sulla produzione.

La CI prova realmente pg_dump/pg_restore su PostgreSQL isolato e integrità/cifratura dei documenti sintetici. Questo non certifica il ripristino dell'archivio di produzione: resta da provare con il primo backup reale.

Collaudo utenti: due corrieri simultanei vedono esclusivamente proprie missioni; agente e ufficio inseriscono operazioni distinte; doppio tap sullo stesso scarico deve produrre un solo addebito; due scarichi sullo stesso codice/lotto devono rispettare i lock del magazzino; nessun prezzo o anomalia deve andare perso. Su telefoni reali controllare leggibilità codici/lotti/QR dopo compressione, GPS, firma, caricamenti multipli e riapertura dopo sospensione. Nessun uso operativo definitivo dichiarato prima di queste prove.

## Accesso server al database

Applicare `sql/server_only_security.sql`: tabelle public con RLS, permessi diretti revocati ad anon/authenticated, RPC SECURITY DEFINER disponibili solo al server, vista WMS con security_invoker e search_path del trigger stock fissato. Questa architettura usa login/permessi OrthoFlow nel server Python; non aggiungere policy "allow all" per risolvere un errore. I client server devono avere la chiave service_role/secret; la publishable/anon key non può gestire dati applicativi. Mai inviare la chiave privilegiata al browser. La migrazione preserva gli accessi dei proprietari e di service_role; non elimina dati e non cambia quantità/prezzi.
