-- Disposable CI database only. All inserted fixtures rolled back.
BEGIN;
DO $$
DECLARE
 header jsonb := '{"data_intervento":"2026-10-13","codice_cliente":"TEST","cliente":"TEST","magazzino_scarico":"LABEL_TEST","count_verified":true,"physical_label_count":2,"included_label_ids":["one","two"]}';
 rows jsonb := '[{"codice":"292.720S","lotto":"LABELLOT","scadenza":"2036-03-01","quantita":2,"label_ids":["one","two"],"verificata":true,"prezzo":1}]';
 result jsonb; failed boolean; before_count bigint;
BEGIN
 INSERT INTO giacenze(codice_magazzino,codice,lotto,scadenza,quantita,origine)
 VALUES('LABEL_TEST','292720S','LABELLOT','2036-03-01',2,'CONTO DEPOSITO');
 result := crea_intervento_scarico_ai_verificato(header,rows,'TEST');
 IF (SELECT quantita FROM giacenze WHERE codice_magazzino='LABEL_TEST')<>0 THEN
   RAISE EXCEPTION 'duplicate physical pieces were not discharged as 2';
 END IF;
 IF EXISTS(SELECT 1 FROM giacenze WHERE codice_magazzino='LABEL_TEST' AND origine='SCARICO SALA AI') THEN
   RAISE EXCEPTION 'artificial stock created by movement trigger';
 END IF;
 IF (SELECT quantita FROM righe_intervento WHERE intervento_id=(result->>'intervento_id')::bigint)<>2 THEN
   RAISE EXCEPTION 'wrong aggregated quantity';
 END IF;
 SELECT count(*) INTO before_count FROM interventi;
 result:=crea_intervento_scarico_ai_verificato(header,rows,'TEST');
 IF (SELECT count(*) FROM interventi)<>before_count+1 OR (result->>'anomalie')::int<>1 THEN
   RAISE EXCEPTION 'shortage must save intervention and anomaly';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM anomalie_giacenza WHERE intervento_id=(result->>'intervento_id')::bigint AND motivo LIKE 'GIACENZA_INSUFFICIENTE%' AND quantita_richiesta=2 AND quantita_disponibile=0) THEN
   RAISE EXCEPTION 'shortage evidence missing';
 END IF;
 IF EXISTS(SELECT 1 FROM movimenti_magazzino WHERE riferimento_id=result->>'intervento_id' AND riferimento_tipo='INTERVENTO') THEN
   RAISE EXCEPTION 'anomaly created a stock movement';
 END IF;
 failed:=false;
 BEGIN
   PERFORM crea_intervento_scarico_ai_verificato(header || '{"count_verified":false}',rows,'TEST');
 EXCEPTION WHEN OTHERS THEN
   IF SQLERRM NOT LIKE '%ETICHETTE_NON_VERIFICATE%' THEN RAISE; END IF;
   failed:=true;
 END;
 IF NOT failed THEN RAISE EXCEPTION 'unverified count accepted'; END IF;
 failed:=false;
 BEGIN
   PERFORM crea_intervento_scarico_ai_verificato(header,
      jsonb_set(rows,'{0,label_ids}','["one","one"]'),'TEST');
 EXCEPTION WHEN OTHERS THEN
   IF SQLERRM NOT LIKE '%IDENTITA_FISICHE_DUPLICATE%' THEN RAISE; END IF;
   failed:=true;
 END;
 IF NOT failed THEN RAISE EXCEPTION 'artificial duplicate accepted'; END IF;
 UPDATE giacenze SET quantita=2,scadenza='2036-04-01' WHERE codice_magazzino='LABEL_TEST';
 result:=crea_intervento_scarico_ai_verificato(header,rows,'TEST');
 IF (result->>'anomalie')::int<>1 OR (SELECT quantita FROM giacenze WHERE codice_magazzino='LABEL_TEST')<>2
    OR NOT EXISTS(SELECT 1 FROM anomalie_giacenza WHERE intervento_id=(result->>'intervento_id')::bigint AND motivo LIKE 'SCADENZA_DIVERSA_O_MANCANTE%2036-03-01') THEN
   RAISE EXCEPTION 'expiry mismatch must preserve stock and save anomaly';
 END IF;
 result:=crea_intervento_scarico_ai_verificato(header,jsonb_set(rows,'{0,lotto}','"MISSINGLOT"'),'TEST');
 IF (result->>'anomalie')::int<>1 OR NOT EXISTS(SELECT 1 FROM anomalie_giacenza WHERE intervento_id=(result->>'intervento_id')::bigint AND lotto='MISSINGLOT' AND motivo LIKE 'LOTTO_NON_CORRISPONDENTE%') THEN
   RAISE EXCEPTION 'missing lot must save exact label and anomaly';
 END IF;
 UPDATE giacenze SET quantita=1,scadenza='2036-03-01' WHERE codice_magazzino='LABEL_TEST';
 result:=crea_intervento_scarico_ai_verificato(header,rows,'TEST');
 IF (SELECT quantita FROM giacenze WHERE codice_magazzino='LABEL_TEST')<>1
    OR NOT EXISTS(SELECT 1 FROM anomalie_giacenza WHERE intervento_id=(result->>'intervento_id')::bigint AND quantita_richiesta=2 AND quantita_disponibile=1) THEN
   RAISE EXCEPTION 'insufficient aggregate stock was partially debited';
 END IF;
 -- A mixed intervention saves both the matching stock discharge and an anomaly.
 result:=crea_intervento_scarico_ai_verificato(header,
   '[{"codice":"292.720S","lotto":"LABELLOT","scadenza":"2036-03-01","quantita":1,"label_ids":["one"],"verificata":true,"prezzo":1},
     {"codice":"292.720S","lotto":"MISSINGLOT","scadenza":"2036-03-01","quantita":1,"label_ids":["two"],"verificata":true,"prezzo":1}]','TEST');
 IF (result->>'righe')::int<>2 OR (result->>'anomalie')::int<>1
    OR (SELECT quantita FROM giacenze WHERE codice_magazzino='LABEL_TEST')<>0
    OR (SELECT count(*) FROM movimenti_magazzino WHERE riferimento_tipo='INTERVENTO' AND riferimento_id=result->>'intervento_id')<>1 THEN
   RAISE EXCEPTION 'mixed intervention must discharge only its matching row';
 END IF;
 failed:=false;
 BEGIN
   PERFORM crea_intervento_scarico_ai_verificato(header,
      jsonb_set(jsonb_set(rows,'{0,codice}','"292.720"'),'{0,is_sterile}','true'),'TEST');
 EXCEPTION WHEN OTHERS THEN
   IF SQLERRM NOT LIKE '%REF_STERILE_SENZA_SUFFISSO%' THEN RAISE; END IF;
   failed:=true;
 END;
 IF NOT failed THEN RAISE EXCEPTION 'missing sterile suffix accepted'; END IF;
 failed:=false;
 BEGIN
   PERFORM crea_intervento_scarico_ai_verificato(header,
      jsonb_set(jsonb_set(rows,'{0,senza_lotto}','true'),'{0,is_sterile}','true'),'TEST');
 EXCEPTION WHEN OTHERS THEN
   IF SQLERRM NOT LIKE '%STERILE_SENZA_LOTTO_NON_AMMESSO%' THEN RAISE; END IF;
   failed:=true;
 END;
 IF NOT failed THEN RAISE EXCEPTION 'sterile lotless bypass accepted'; END IF;
 IF has_function_privilege('anon','crea_intervento_scarico_ai_verificato(jsonb,jsonb,text)','EXECUTE')
    OR has_function_privilege('authenticated','crea_intervento_scarico_ai_verificato(jsonb,jsonb,text)','EXECUTE') THEN
   RAISE EXCEPTION 'verified RPC publicly callable';
 END IF;
END $$;
ROLLBACK;
