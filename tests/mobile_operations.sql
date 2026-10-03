BEGIN;
INSERT INTO utenti_app(id,username,ruolo,permessi,agente_nome) VALUES
 (90001,'mobile-courier','Corriere',ARRAY['CORRIERE'],NULL),
 (90002,'mobile-other','Corriere',ARRAY['CORRIERE'],NULL),
 (90003,'mobile-agent','Agente',ARRAY['AGENTE'],'Mobile Agent');
INSERT INTO corrieri(id,user_id) VALUES(90001,90001),(90002,90002);
INSERT INTO missioni_corrieri(id,codice,corriere_id,struttura_id,tipo,kit_codice) VALUES(90001,'mobile-test',90001,1,'RITIRO','MOBILE-KIT');
INSERT INTO kit_logistici(id,codice,stato,codice_magazzino) VALUES(90001,'MOBILE-KIT','ASSEGNATO','MOBILE-MAG');
INSERT INTO clienti(codice_cliente,agente) VALUES('9010013','Mobile Agent');
SET LOCAL ROLE service_role;
DO $$ DECLARE a jsonb; b jsonb; BEGIN
 BEGIN
  PERFORM orthoflow_mobile_mission(90002,90001,'STAMP','{"latitude":41,"longitude":14,"accuracy":10}');
  RAISE EXCEPTION 'Unauthorized mission access succeeded';
 EXCEPTION WHEN raise_exception THEN IF SQLERRM<>'MOBILE_MISSION_UNAVAILABLE' THEN RAISE; END IF; END;
 PERFORM orthoflow_mobile_mission(90001,90001,'STAMP','{"latitude":41,"longitude":14,"accuracy":10}');
 PERFORM orthoflow_mobile_mission(90001,90001,'STAMP','{"latitude":41,"longitude":14,"accuracy":10}');
 IF (SELECT count(*) FROM timbrature_corrieri WHERE missione_id=90001)<>1 THEN RAISE EXCEPTION 'Repeated stamp duplicated'; END IF;
 IF (SELECT stato FROM kit_logistici WHERE id=90001)<>'DA_RITIRARE' THEN RAISE EXCEPTION 'Kit not updated atomically'; END IF;
 BEGIN
  PERFORM orthoflow_mobile_mission(90001,90001,'COMPLETE','{"signature_status":"CON_FIRMA"}');
  RAISE EXCEPTION 'Unsigned pickup succeeded';
 EXCEPTION WHEN raise_exception THEN IF SQLERRM<>'MOBILE_CERTIFICATE_REQUIRED' THEN RAISE; END IF; END;
 IF (SELECT stato FROM missioni_corrieri WHERE id=90001)<>'ARRIVATO' THEN RAISE EXCEPTION 'Invalid completion changed mission'; END IF;
 PERFORM orthoflow_mobile_mission(90001,90001,'COMPLETE','{"signature_status":"SENZA_FIRMA","note":"Referente assente"}');
 PERFORM orthoflow_mobile_mission(90001,90001,'COMPLETE','{"signature_status":"SENZA_FIRMA"}');
 IF (SELECT count(*) FROM movimenti_kit_corrieri WHERE missione_id=90001)<>2 THEN RAISE EXCEPTION 'Completion duplicated kit movements'; END IF;
 IF (SELECT stato FROM kit_logistici WHERE id=90001)<>'RITIRATO' THEN RAISE EXCEPTION 'Pickup state wrong'; END IF;
 a:=orthoflow_mobile_scarico(90003,'request-test-12345678',
  '{"data_intervento":"2026-10-03","codice_cliente":"9010013","cliente":"Mobile Malzoni","linea":"TRAUMA","magazzino_scarico":"MOBILE-MAG"}',
  '[{"codice":"1504-00-126","lotto":"","senza_lotto":true,"quantita":2,"prezzo":100,"prezzo_source":"MANUALE_MEMORIZZATO","conto_deposito_struttura":true}]');
 b:=orthoflow_mobile_scarico(90003,'request-test-12345678',
  '{"data_intervento":"2026-10-03","codice_cliente":"9010013","cliente":"Mobile Malzoni","linea":"TRAUMA","magazzino_scarico":"MOBILE-MAG"}',
  '[{"codice":"1504-00-126","lotto":"","senza_lotto":true,"quantita":2,"prezzo":100,"prezzo_source":"MANUALE_MEMORIZZATO","conto_deposito_struttura":true}]');
 IF a<>b OR (SELECT count(*) FROM orthoflow_mobile_operations WHERE user_id=90003)<>1 THEN RAISE EXCEPTION 'Duplicate scarico'; END IF;
 IF (a->>'totale')::numeric<>200 THEN RAISE EXCEPTION 'Malzoni revenue lost'; END IF;
 IF EXISTS(SELECT 1 FROM reintegri_kit WHERE kit_id=90001) THEN RAISE EXCEPTION 'Structure stock generated own reintegration'; END IF;
 IF EXISTS(SELECT 1 FROM anomalie_giacenza WHERE intervento_id=(a->>'intervento_id')::bigint) THEN RAISE EXCEPTION 'Structure stock generated stock anomaly'; END IF;
 BEGIN
  PERFORM orthoflow_mobile_scarico(90003,'request-other-123456',
   '{"data_intervento":"2026-10-03","codice_cliente":"OTHER","linea":"TRAUMA"}','[]');
  RAISE EXCEPTION 'Other customer succeeded';
 EXCEPTION WHEN raise_exception THEN IF SQLERRM<>'MOBILE_CUSTOMER_UNAVAILABLE' THEN RAISE; END IF; END;
END $$;
RESET ROLE;
DO $$ BEGIN
 IF has_function_privilege('anon','public.orthoflow_mobile_mission(bigint,bigint,text,jsonb)','EXECUTE')
  OR has_function_privilege('authenticated','public.orthoflow_mobile_scarico(bigint,text,jsonb,jsonb)','EXECUTE') THEN
  RAISE EXCEPTION 'Mobile functions publicly executable'; END IF;
 IF has_table_privilege('anon','public.orthoflow_mobile_operations','SELECT') THEN RAISE EXCEPTION 'Public session operation access'; END IF;
END $$;
ROLLBACK;
