BEGIN;
DO $test$
DECLARE iid bigint; a bigint; r1 bigint; r2 bigint;
BEGIN
 INSERT INTO interventi(data_intervento,codice_cliente,cliente,linea) VALUES(current_date,'9010013','TEST STRUCTURE ANOMALY','PROTESICA') RETURNING id INTO iid;
 INSERT INTO righe_intervento(intervento_id,codice,lotto,quantita,origine) VALUES(iid,'TEST-STRUCT','TEST',1,'CONTO DEPOSITO') RETURNING id INTO r1;
 INSERT INTO righe_intervento(intervento_id,codice,lotto,quantita,origine) VALUES(iid,'TESTSTRUCT','TEST',1,'CONTO DEPOSITO') RETURNING id INTO r2;
 INSERT INTO anomalie_giacenza(intervento_id,codice,lotto,stato) VALUES(iid,'TESTSTRUCT','TEST','DA_VERIFICARE') RETURNING id INTO a;
 UPDATE righe_intervento SET origine='CONTO DEPOSITO STRUTTURA' WHERE id=r1;
 IF (SELECT stato FROM anomalie_giacenza WHERE id=a)<>'DA_VERIFICARE' THEN RAISE EXCEPTION 'Mixed stock anomaly closed'; END IF;
 UPDATE righe_intervento SET origine='CONTO DEPOSITO STRUTTURA' WHERE id=r2;
 IF (SELECT stato FROM anomalie_giacenza WHERE id=a)<>'RISOLTA' THEN RAISE EXCEPTION 'Confirmed structure anomaly not closed'; END IF;
END $test$;
ROLLBACK;
