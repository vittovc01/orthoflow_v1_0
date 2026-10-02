BEGIN;
DO $test$
DECLARE code text:='LOTLESS'||upper(replace(gen_random_uuid()::text,'-','')); head jsonb; rowdata jsonb; result jsonb; iid bigint; qty numeric; n integer;
BEGIN
 head:=jsonb_build_object('data_intervento','2026-10-02','codice_cliente','9010013','cliente','TEST LOTLESS','linea','TRAUMA','magazzino_scarico','TEST_LOTLESS');
 INSERT INTO giacenze(codice_magazzino,codice,lotto,quantita,origine) VALUES
 ('TEST_LOTLESS',code||'-01','',2,'CONTO DEPOSITO'),
 ('TEST_LOTLESS',code||'01','',3,'CONTO DEPOSITO'),
 ('TEST_LOTLESS',code||'01','REALLOT',10,'CONTO DEPOSITO');
 rowdata:=jsonb_build_object('codice',code||'-01','lotto','','quantita',4,'prezzo',30,'senza_lotto',true);
 result:=crea_intervento_scarico_ai_flessibile(head,jsonb_build_array(rowdata),'TEST_LOTLESS');
 iid:=(result->>'intervento_id')::bigint;
 SELECT sum(quantita) INTO qty FROM giacenze WHERE codice_magazzino='TEST_LOTLESS' AND regexp_replace(upper(codice),'[^A-Z0-9]','','g')=code||'01' AND coalesce(trim(lotto),'')='';
 IF qty IS DISTINCT FROM 1 THEN RAISE EXCEPTION 'Lotless allocation wrong %',qty; END IF;
 IF (SELECT quantita FROM giacenze WHERE codice=code||'01' AND lotto='REALLOT')<>10 THEN RAISE EXCEPTION 'Real lot consumed'; END IF;
 IF EXISTS(SELECT 1 FROM giacenze WHERE codice_magazzino='TEST_LOTLESS' AND origine='SCARICO SALA AI') THEN RAISE EXCEPTION 'Double debit'; END IF;
 IF NOT EXISTS(SELECT 1 FROM righe_intervento WHERE intervento_id=iid AND lotto='' AND validazione like '%Non sterile senza lotto%') THEN RAISE EXCEPTION 'Lotless confirmation not saved'; END IF;
 IF (result->>'totale')::numeric<>120 THEN RAISE EXCEPTION 'Revenue wrong'; END IF;
 result:=crea_intervento_scarico_ai_flessibile(head,jsonb_build_array(rowdata),'TEST_LOTLESS');
 iid:=(result->>'intervento_id')::bigint;
 IF NOT EXISTS(SELECT 1 FROM anomalie_giacenza WHERE intervento_id=iid AND quantita_disponibile=1) THEN RAISE EXCEPTION 'Missing lotless shortage'; END IF;
 IF EXISTS(SELECT 1 FROM movimenti_magazzino WHERE riferimento_tipo='INTERVENTO' AND riferimento_id=iid::text) THEN RAISE EXCEPTION 'Shortage debited'; END IF;
 SELECT count(*) INTO n FROM interventi WHERE codice_cliente='9010013';
 BEGIN
  PERFORM crea_intervento_scarico_ai_flessibile(head,jsonb_build_array(rowdata-'senza_lotto'),'TEST_LOTLESS');
  RAISE EXCEPTION 'Unconfirmed empty lot accepted';
 EXCEPTION WHEN raise_exception THEN
  IF sqlerrm<>'LOTTO_OBBLIGATORIO_O_CONFERMA_NON_STERILE' THEN RAISE; END IF;
 END;
 IF (SELECT count(*) FROM interventi WHERE codice_cliente='9010013')<>n THEN RAISE EXCEPTION 'Failed validation left header'; END IF;
 result:=crea_intervento_scarico_ai_flessibile(head,jsonb_build_array(rowdata||jsonb_build_object('conto_deposito_struttura',true)),'TEST_LOTLESS');
 iid:=(result->>'intervento_id')::bigint;
 IF EXISTS(SELECT 1 FROM anomalie_giacenza WHERE intervento_id=iid) OR EXISTS(SELECT 1 FROM movimenti_magazzino WHERE riferimento_tipo='INTERVENTO' AND riferimento_id=iid::text) THEN RAISE EXCEPTION 'Structure lotless stock touched'; END IF;
END $test$;
ROLLBACK;
