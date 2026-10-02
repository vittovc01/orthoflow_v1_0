BEGIN;
DO $test$
DECLARE code text:='ONCE'||upper(replace(gen_random_uuid()::text,'-',''));
 result jsonb; iid bigint; qty numeric; n integer;
BEGIN
 INSERT INTO giacenze(codice_magazzino,codice,lotto,quantita,origine)
 VALUES('TEST_ONCE',code||'01','TEST',10,'CONTO DEPOSITO');
 result:=crea_intervento_scarico_ai_flessibile(
 jsonb_build_object('data_intervento','2026-10-02','codice_cliente','9010013','cliente','TEST ONCE','linea','PROTESICA','magazzino_scarico','TEST_ONCE'),
 jsonb_build_array(jsonb_build_object('codice',code||'-01','lotto','TEST','quantita',2,'prezzo',30,'conto_deposito_struttura',false)),'TEST_ONCE');
 iid:=(result->>'intervento_id')::bigint;
 SELECT sum(quantita) INTO qty FROM giacenze WHERE codice_magazzino='TEST_ONCE'
 AND regexp_replace(upper(codice),'[^A-Z0-9]','','g')=code||'01';
 IF qty IS DISTINCT FROM 8 THEN RAISE EXCEPTION 'Double stock debit: %',qty; END IF;
 IF EXISTS(SELECT 1 FROM giacenze WHERE codice_magazzino='TEST_ONCE' AND origine='SCARICO SALA AI')
 THEN RAISE EXCEPTION 'Artificial stock row created'; END IF;
 SELECT count(*) INTO n FROM movimenti_magazzino WHERE riferimento_tipo='INTERVENTO' AND riferimento_id=iid::text;
 IF n<>1 OR (result->>'totale')::numeric<>60 THEN RAISE EXCEPTION 'Missing movement or wrong revenue'; END IF;
 -- Repeated same item consumes another two, exactly once.
 result:=crea_intervento_scarico_ai_flessibile(
 jsonb_build_object('data_intervento','2026-10-02','codice_cliente','9010013','cliente','TEST ONCE','linea','PROTESICA','magazzino_scarico','TEST_ONCE'),
 jsonb_build_array(jsonb_build_object('codice',code||'-01','lotto','TEST','quantita',2,'prezzo',30)),'TEST_ONCE');
 SELECT sum(quantita) INTO qty FROM giacenze WHERE codice_magazzino='TEST_ONCE'
 AND regexp_replace(upper(codice),'[^A-Z0-9]','','g')=code||'01';
 IF qty IS DISTINCT FROM 6 THEN RAISE EXCEPTION 'Repeated stock debit wrong: %',qty; END IF;
 -- Structure stock creates revenue but no stock movement.
 result:=crea_intervento_scarico_ai_flessibile(
 jsonb_build_object('data_intervento','2026-10-02','codice_cliente','9010013','cliente','TEST ONCE','linea','PROTESICA','magazzino_scarico','TEST_ONCE'),
 jsonb_build_array(jsonb_build_object('codice',code||'-01','lotto','TEST','quantita',2,'prezzo',30,'conto_deposito_struttura',true)),'TEST_ONCE');
 iid:=(result->>'intervento_id')::bigint;
 IF EXISTS(SELECT 1 FROM movimenti_magazzino WHERE riferimento_tipo='INTERVENTO' AND riferimento_id=iid::text)
 OR (result->>'totale')::numeric<>60 THEN RAISE EXCEPTION 'Structure branch broken'; END IF;
 -- Insufficient stock leaves availability unchanged and records the anomaly.
 result:=crea_intervento_scarico_ai_flessibile(
 jsonb_build_object('data_intervento','2026-10-02','codice_cliente','9010013','cliente','TEST ONCE','linea','PROTESICA','magazzino_scarico','TEST_ONCE'),
 jsonb_build_array(jsonb_build_object('codice',code||'-01','lotto','TEST','quantita',7,'prezzo',30)),'TEST_ONCE');
 iid:=(result->>'intervento_id')::bigint;
 IF EXISTS(SELECT 1 FROM movimenti_magazzino WHERE riferimento_tipo='INTERVENTO' AND riferimento_id=iid::text)
 OR NOT EXISTS(SELECT 1 FROM anomalie_giacenza WHERE intervento_id=iid) THEN RAISE EXCEPTION 'Insufficient-stock branch broken'; END IF;
 SELECT quantita INTO qty FROM giacenze WHERE codice_magazzino='TEST_ONCE' AND codice=code||'01' AND origine='CONTO DEPOSITO';
 IF qty IS DISTINCT FROM 6 THEN RAISE EXCEPTION 'Wrong final stock'; END IF;
 -- Other movement paths still use the trigger.
 INSERT INTO movimenti_magazzino(tipo_movimento,codice_magazzino,codice,lotto,quantita,origine,riferimento_tipo)
 VALUES('CARICO','TEST_ONCE',code||'OTHER','TEST',5,'CONTO DEPOSITO','TEST');
 INSERT INTO movimenti_magazzino(tipo_movimento,codice_magazzino,codice,lotto,quantita,origine,riferimento_tipo)
 VALUES('RETTIFICA_INTERVENTO','TEST_ONCE',code||'OTHER','TEST',-1,'CONTO DEPOSITO','INTERVENTO');
 SELECT quantita INTO qty FROM giacenze WHERE codice_magazzino='TEST_ONCE' AND codice=code||'OTHER' AND origine='CONTO DEPOSITO';
 IF qty IS DISTINCT FROM 4 THEN RAISE EXCEPTION 'Normal trigger broken'; END IF;
END $test$;

ROLLBACK;
