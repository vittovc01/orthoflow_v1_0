-- Isolated CI database only. All test records rolled back.
BEGIN;
DO $$
DECLARE
 h jsonb := '{"data_intervento":"2026-10-21","codice_cliente":"9010054","cliente":"TEST CTO","cartella_clinica":"TEST-CTO-ROLLBACK","linea":"TRAUMA","magazzino_scarico":"CTO_TEST","request_id":"00000000-0000-4000-8000-000000000054","count_verified":true,"physical_label_count":2,"reported_label_count":2,"included_label_ids":["own","hospital"],"label_manifest":[{"label_id":"own","codice":"CTO-OWN","lotto":"LOT-A","scadenza":"2035-01-01","quantita":1},{"label_id":"hospital","codice":"CTO-HOSPITAL","lotto":"LOT-B","scadenza":"2035-01-01","quantita":1}]}';
 rows jsonb := '[{"codice":"CTO-OWN","lotto":"LOT-A","scadenza":"2035-01-01","quantita":1,"label_ids":["own"],"verificata":true,"prezzo":10},{"codice":"CTO-HOSPITAL","lotto":"LOT-B","scadenza":"2035-01-01","quantita":1,"label_ids":["hospital"],"verificata":true,"prezzo":20,"conto_deposito_struttura":true}]';
 result jsonb; i bigint; n bigint; failed boolean:=false;
BEGIN
 INSERT INTO giacenze(codice_magazzino,codice,lotto,scadenza,quantita,origine)
 VALUES('CTO_TEST','CTO-OWN','LOT-A','2035-01-01',5,'CONTO DEPOSITO');
 result:=crea_intervento_scarico_ai_verificato_v2(h,rows,'TEST');
 i:=(result->>'intervento_id')::bigint;
 IF (result->>'totale')::numeric<>30 OR (result->>'righe')::int<>2 THEN RAISE EXCEPTION 'CTO revenue lost'; END IF;
 IF (SELECT quantita FROM giacenze WHERE codice_magazzino='CTO_TEST' AND codice='CTO-OWN')<>4 THEN RAISE EXCEPTION 'own stock debit'; END IF;
 IF (SELECT count(*) FROM movimenti_magazzino WHERE riferimento_id=i::text AND riferimento_tipo='INTERVENTO')<>1 THEN RAISE EXCEPTION 'hospital created stock movement'; END IF;
 IF EXISTS(SELECT 1 FROM anomalie_giacenza WHERE intervento_id=i AND stato='DA_VERIFICARE') THEN RAISE EXCEPTION 'hospital stock anomaly'; END IF;
 IF NOT EXISTS(SELECT 1 FROM righe_intervento WHERE intervento_id=i AND codice='CTO-HOSPITAL' AND origine='CONTO DEPOSITO STRUTTURA' AND totale=20) THEN RAISE EXCEPTION 'ownership not saved'; END IF;
 result:=crea_intervento_scarico_ai_verificato_v2(h,rows,'TEST');
 IF NOT (result->>'replayed')::boolean OR (SELECT quantita FROM giacenze WHERE codice_magazzino='CTO_TEST' AND codice='CTO-OWN')<>4 THEN RAISE EXCEPTION 'CTO replay debited twice'; END IF;
 -- A CTO-owned product cannot be silently reassigned even to enabled Malzoni.
 BEGIN
  UPDATE interventi SET codice_cliente='9010013' WHERE id=i;
 EXCEPTION WHEN raise_exception THEN failed:=true;
 END;
 IF NOT failed OR (SELECT codice_cliente FROM interventi WHERE id=i)<>'9010054' THEN RAISE EXCEPTION 'hospital ownership reassigned'; END IF;
 -- Line-only changes at the same hospital still reprice normally.
 UPDATE interventi SET linea='PROTESICA' WHERE id=i;
 INSERT INTO anomalie_giacenza(codice,lotto,intervento_id,stato,motivo)
 VALUES('CTO-HOSPITAL','LOT-B',i,'DA_VERIFICARE','TEST');
 UPDATE righe_intervento SET origine='CONTO DEPOSITO STRUTTURA' WHERE intervento_id=i AND codice='CTO-HOSPITAL';
 IF EXISTS(SELECT 1 FROM anomalie_giacenza WHERE intervento_id=i AND codice='CTO-HOSPITAL' AND stato='DA_VERIFICARE') THEN RAISE EXCEPTION 'CTO structure anomaly not closed'; END IF;
 IF has_function_privilege('anon','public.crea_intervento_scarico_ai_verificato_v2(jsonb,jsonb,text)','EXECUTE') OR has_function_privilege('authenticated','public.crea_intervento_scarico_ai_verificato_v2(jsonb,jsonb,text)','EXECUTE') THEN RAISE EXCEPTION 'public discharge endpoint'; END IF;
END $$;
ROLLBACK;
