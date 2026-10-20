BEGIN;
DO $$
DECLARE i bigint; a bigint; b bigint; c bigint; d bigint; r1 bigint; r2 bigint; r3 bigint; r4 bigint; r5 bigint; before_stock bigint; n bigint; failed boolean:=false;
BEGIN
 INSERT INTO interventi(codice_cliente,linea,data_intervento) VALUES('TEST-OLD','TRAUMA','2026-10-20') RETURNING id INTO i;
 INSERT INTO righe_intervento(intervento_id,codice,lotto,quantita,prezzo,totale,valore,prezzo_source,prezzo_verificato_da,prezzo_verificato_at)
 VALUES(i,'1504-00-126','LOT1',2,90,180,180,'MANUALE','old-user',now()) RETURNING id INTO r1;
 INSERT INTO righe_intervento(intervento_id,codice,lotto,quantita,prezzo,totale,valore)
 VALUES(i,'MISSING','LOT2',1,500,500,500) RETURNING id INTO r2;
 INSERT INTO righe_intervento(intervento_id,codice,lotto,quantita,prezzo,totale,valore)
 VALUES(i,'FREE','LOT3',3,80,240,240) RETURNING id INTO r3;
 INSERT INTO righe_intervento(intervento_id,codice,lotto,quantita,prezzo,totale,valore)
 VALUES(i,'CONFLICT','LOT4',1,80,80,80) RETURNING id INTO r4;
 INSERT INTO righe_intervento(intervento_id,codice,lotto,quantita,prezzo,totale,valore)
 VALUES(i,'NULLPRICE','LOT5',1,80,80,80) RETURNING id INTO r5;
 INSERT INTO offerte_header(linea,data_inizio,data_fine,stato_record) VALUES('TRAUMA','2026-01-01','2026-12-31','Attivo') RETURNING id INTO a;
 INSERT INTO offerte_clienti(offerta_id,codice_cliente) VALUES(a,'TEST-NEW');
 INSERT INTO offerte_prezzi(offerta_id,codice,prezzo) VALUES(a,'150400126',12.5),(a,'FREE',0),(a,'CONFLICT',40),(a,'NULLPRICE',NULL);
 INSERT INTO offerte_header(linea,stato_record) VALUES('TRAUMA','Attivo') RETURNING id INTO b;
 INSERT INTO offerte_clienti(offerta_id,codice_cliente) VALUES(b,'TEST-NEW');
 INSERT INTO offerte_prezzi(offerta_id,codice,prezzo) VALUES(b,'CONFLICT',41);
 INSERT INTO offerte_header(linea,data_fine,stato_record) VALUES('TRAUMA','2020-01-01','Attivo') RETURNING id INTO c;
 INSERT INTO offerte_clienti(offerta_id,codice_cliente) VALUES(c,'TEST-NEW');
 INSERT INTO offerte_prezzi(offerta_id,codice,prezzo) VALUES(c,'150400126',999),(c,'MISSING',999);
 INSERT INTO offerte_header(linea,stato_record) VALUES('PROTESICA','Attivo') RETURNING id INTO d;
 INSERT INTO offerte_clienti(offerta_id,codice_cliente) VALUES(d,'TEST-NEW');
 INSERT INTO offerte_prezzi(offerta_id,codice,prezzo) VALUES(d,'150400126',22);
 SELECT count(*) INTO before_stock FROM movimenti_magazzino;
 IF NOT EXISTS(SELECT 1 FROM public.anteprima_prezzi_cambio_struttura(i,'TEST-NEW','TRAUMA','2026-10-20') WHERE riga_id=r1 AND prezzo_nuovo=12.5 AND totale_nuovo=25) THEN RAISE EXCEPTION 'preview normalized match'; END IF;
 IF (SELECT prezzo FROM righe_intervento WHERE id=r1)<>90 THEN RAISE EXCEPTION 'preview wrote data'; END IF;
 UPDATE interventi SET codice_cliente='TEST-NEW' WHERE id=i;
 IF NOT EXISTS(SELECT 1 FROM righe_intervento WHERE id=r1 AND prezzo=12.5 AND totale=25 AND valore=25 AND prezzo_source='OFFERTA' AND prezzo_verificato_da IS NULL AND prezzo_verificato_at IS NULL) THEN RAISE EXCEPTION 'reprice manual line'; END IF;
 IF NOT EXISTS(SELECT 1 FROM righe_intervento WHERE id=r2 AND prezzo IS NULL AND totale IS NULL AND valore IS NULL AND prezzo_source='RICALCOLO_SENZA_OFFERTA') THEN RAISE EXCEPTION 'missing inherited old price'; END IF;
 IF NOT EXISTS(SELECT 1 FROM righe_intervento WHERE id=r3 AND prezzo=0 AND totale=0 AND valore=0) THEN RAISE EXCEPTION 'zero is valid'; END IF;
 IF EXISTS(SELECT 1 FROM righe_intervento WHERE id IN(r4,r5) AND prezzo IS NOT NULL) THEN RAISE EXCEPTION 'conflict or null silently priced'; END IF;
 SELECT count(*) INTO n FROM audit_log WHERE azione='RICALCOLO_PREZZO_STRUTTURA' AND (dettagli::jsonb->>'intervento_id')::bigint=i;
 IF n<>5 THEN RAISE EXCEPTION 'missing per-row audit'; END IF;
 UPDATE interventi SET codice_cliente='TEST-NEW' WHERE id=i;
 IF (SELECT count(*) FROM audit_log WHERE azione='RICALCOLO_PREZZO_STRUTTURA' AND (dettagli::jsonb->>'intervento_id')::bigint=i)<>n THEN RAISE EXCEPTION 'same customer repriced'; END IF;
 UPDATE interventi SET linea='PROTESICA' WHERE id=i;
 IF (SELECT prezzo FROM righe_intervento WHERE id=r1)<>22 THEN RAISE EXCEPTION 'line offer'; END IF;
 UPDATE interventi SET codice_cliente='NO-OFFER' WHERE id=i;
 IF EXISTS(SELECT 1 FROM righe_intervento WHERE intervento_id=i AND prezzo IS NOT NULL) THEN RAISE EXCEPTION 'no-offer retains prices'; END IF;
 IF (SELECT count(*) FROM movimenti_magazzino)<>before_stock THEN RAISE EXCEPTION 'stock changed'; END IF;
 -- Inject a failure on the second row, after the first price update.
 UPDATE righe_intervento SET prezzo=77 WHERE id=r2;
 EXECUTE format('ALTER TABLE public.righe_intervento ADD CONSTRAINT ci_reprice_failure CHECK (id<>%s OR prezzo IS NOT NULL) NOT VALID',r2);
 SELECT count(*) INTO n FROM audit_log WHERE azione='RICALCOLO_PREZZO_STRUTTURA';
 BEGIN
  UPDATE interventi SET codice_cliente='TEST-NEW',linea='TRAUMA' WHERE id=i;
 EXCEPTION WHEN check_violation THEN failed:=true;
 END;
 IF NOT failed OR (SELECT codice_cliente FROM interventi WHERE id=i)<>'NO-OFFER'
   OR (SELECT prezzo FROM righe_intervento WHERE id=r1) IS NOT NULL
   OR (SELECT prezzo FROM righe_intervento WHERE id=r2)<>77
   OR (SELECT count(*) FROM audit_log WHERE azione='RICALCOLO_PREZZO_STRUTTURA')<>n
 THEN RAISE EXCEPTION 'partial write after mid-row error'; END IF;
 ALTER TABLE public.righe_intervento DROP CONSTRAINT ci_reprice_failure;
 failed:=false;
 -- A row failure must roll back both header and prices in the same statement.
 INSERT INTO righe_intervento(intervento_id,codice,lotto,quantita,prezzo,totale,valore)
 VALUES(i,'STRUCTURE','LOT6',1,33,33,33);
 UPDATE righe_intervento SET origine='CONTO DEPOSITO STRUTTURA' WHERE intervento_id=i AND codice='STRUCTURE';
 BEGIN
  UPDATE interventi SET codice_cliente='TEST-NEW',linea='TRAUMA' WHERE id=i;
 EXCEPTION WHEN raise_exception THEN failed:=true;
 END;
 IF NOT failed OR (SELECT codice_cliente FROM interventi WHERE id=i)<>'NO-OFFER'
    OR EXISTS(SELECT 1 FROM righe_intervento WHERE id=r1 AND prezzo IS NOT NULL)
 THEN RAISE EXCEPTION 'atomic rollback failed'; END IF;
 IF has_function_privilege('anon','public.anteprima_prezzi_cambio_struttura(bigint,text,text,date)','EXECUTE')
 OR has_function_privilege('authenticated','public.anteprima_prezzi_cambio_struttura(bigint,text,text,date)','EXECUTE')
 THEN RAISE EXCEPTION 'public pricing endpoint'; END IF;
END $$;
ROLLBACK;
