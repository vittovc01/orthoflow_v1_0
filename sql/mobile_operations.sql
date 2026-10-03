-- Server-only RPCs. They use existing operational tables and stock logic.
-- Never call with an anon/publishable key: the HTTP server authenticates utenti_app.
BEGIN;
CREATE TABLE IF NOT EXISTS public.orthoflow_mobile_operations (
 user_id bigint NOT NULL REFERENCES public.utenti_app(id),
 request_id text NOT NULL,
 intervento_id bigint NOT NULL REFERENCES public.interventi(id) ON DELETE CASCADE,
 result jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(user_id,request_id)
);
ALTER TABLE public.orthoflow_mobile_operations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.orthoflow_mobile_operations FROM PUBLIC, anon, authenticated;
GRANT SELECT,INSERT ON public.orthoflow_mobile_operations TO service_role;

CREATE OR REPLACE FUNCTION public.orthoflow_mobile_mission(
 p_user_id bigint,p_mission_id bigint,p_action text,p_payload jsonb DEFAULT '{}'::jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path = public AS $$
DECLARE u utenti_app%ROWTYPE; m missioni_corrieri%ROWTYPE; k kit_logistici%ROWTYPE;
 manager boolean; next_state text; old_state text;
BEGIN
 SELECT * INTO u FROM utenti_app WHERE id=p_user_id FOR SHARE;
 IF NOT FOUND OR NOT u.attivo OR u.stato_accesso<>'APPROVATO' THEN RAISE EXCEPTION 'MOBILE_UNAUTHORIZED'; END IF;
 manager := u.ruolo='Admin' OR 'DIREZIONE'=ANY(u.permessi);
 IF NOT manager AND NOT ('CORRIERE'=ANY(u.permessi)) THEN RAISE EXCEPTION 'MOBILE_UNAUTHORIZED'; END IF;
 SELECT * INTO m FROM missioni_corrieri WHERE id=p_mission_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'MOBILE_MISSION_UNAVAILABLE'; END IF;
 IF NOT manager AND NOT EXISTS(SELECT 1 FROM corrieri WHERE id=m.corriere_id AND user_id=u.id AND attivo) THEN
  RAISE EXCEPTION 'MOBILE_MISSION_UNAVAILABLE';
 END IF;
 IF p_action NOT IN ('STAMP','COMPLETE','PHOTO','CERTIFICATE') THEN RAISE EXCEPTION 'MOBILE_INVALID_ACTION'; END IF;
 IF m.stato='COMPLETATA' THEN
  IF p_action='COMPLETE' THEN RETURN jsonb_build_object('ok',true,'already_completed',true); END IF;
  RAISE EXCEPTION 'MOBILE_MISSION_CLOSED';
 END IF;
 IF m.stato NOT IN ('PROGRAMMATA','ARRIVATO') THEN RAISE EXCEPTION 'MOBILE_INVALID_STATE'; END IF;
 IF p_action='STAMP' THEN
  IF (p_payload->>'latitude') IS NULL OR (p_payload->>'longitude') IS NULL OR (p_payload->>'accuracy') IS NULL
    OR NOT ((p_payload->>'latitude')::numeric BETWEEN -90 AND 90)
    OR NOT ((p_payload->>'longitude')::numeric BETWEEN -180 AND 180)
    OR NOT ((p_payload->>'accuracy')::numeric > 0) THEN RAISE EXCEPTION 'MOBILE_INVALID_GPS'; END IF;
  IF m.stato='ARRIVATO' THEN RETURN jsonb_build_object('ok',true,'already_stamped',true); END IF;
  INSERT INTO timbrature_corrieri(missione_id,corriere_id,struttura_id,tipo,latitudine,longitudine,precisione_m)
  VALUES(m.id,m.corriere_id,m.struttura_id,'ARRIVO',(p_payload->>'latitude')::numeric,(p_payload->>'longitude')::numeric,(p_payload->>'accuracy')::numeric);
  UPDATE missioni_corrieri SET stato='ARRIVATO',updated_at=now() WHERE id=m.id;
  next_state:=CASE WHEN m.tipo='CONSEGNA' THEN 'IN_USCITA' ELSE 'DA_RITIRARE' END;
 ELSIF p_action='PHOTO' THEN
  IF NOT starts_with(p_payload->>'path','missioni/'||m.id||'/foto/') OR (p_payload->>'path') LIKE '%..%' THEN
   RAISE EXCEPTION 'MOBILE_INVALID_PATH'; END IF;
  INSERT INTO foto_missioni(missione_id,tipo,storage_path) VALUES(m.id,m.tipo,p_payload->>'path');
 ELSIF p_action='CERTIFICATE' THEN
  IF m.tipo<>'RITIRO' OR coalesce(trim(p_payload->>'signer'),'')='' OR coalesce(trim(p_payload->>'role'),'')=''
    OR NOT starts_with(p_payload->>'path','missioni/'||m.id||'/documenti/')
    OR NOT starts_with(p_payload->>'signature_path','missioni/'||m.id||'/documenti/') THEN RAISE EXCEPTION 'MOBILE_INVALID_CERTIFICATE'; END IF;
  INSERT INTO documenti_missioni(missione_id,tipo_documento,storage_path,firma_storage_path,nome_firmatario,ruolo_firmatario,firmato_at)
  VALUES(m.id,'CERTIFICAZIONE_LAVAGGIO_DECONTAMINAZIONE',p_payload->>'path',p_payload->>'signature_path',p_payload->>'signer',p_payload->>'role',now());
  UPDATE missioni_corrieri SET esito_firma_ritiro='CON_FIRMA',nota_firma_ritiro=NULL,updated_at=now() WHERE id=m.id;
 ELSIF p_action='COMPLETE' THEN
  IF m.stato<>'ARRIVATO' THEN RAISE EXCEPTION 'MOBILE_STAMP_REQUIRED'; END IF;
  IF m.tipo='RITIRO' THEN
   IF coalesce(p_payload->>'signature_status','') NOT IN ('CON_FIRMA','SENZA_FIRMA') THEN RAISE EXCEPTION 'MOBILE_SIGNATURE_STATUS_REQUIRED'; END IF;
   IF p_payload->>'signature_status'='CON_FIRMA' AND NOT EXISTS(
    SELECT 1 FROM documenti_missioni WHERE missione_id=m.id AND tipo_documento='CERTIFICAZIONE_LAVAGGIO_DECONTAMINAZIONE'
     AND coalesce(firma_storage_path,'')<>'' AND coalesce(nome_firmatario,'')<>'' AND firmato_at IS NOT NULL
   ) THEN RAISE EXCEPTION 'MOBILE_CERTIFICATE_REQUIRED'; END IF;
  END IF;
  UPDATE missioni_corrieri SET stato='COMPLETATA',updated_at=now(),
   esito_firma_ritiro=CASE WHEN m.tipo='RITIRO' THEN p_payload->>'signature_status' ELSE esito_firma_ritiro END,
   nota_firma_ritiro=CASE WHEN m.tipo='RITIRO' AND p_payload->>'signature_status'='SENZA_FIRMA' THEN p_payload->>'note' ELSE NULL END WHERE id=m.id;
  next_state:=CASE WHEN m.tipo='CONSEGNA' THEN 'CONSEGNATO' ELSE 'RITIRATO' END;
 END IF;
 IF next_state IS NOT NULL AND coalesce(trim(m.kit_codice),'')<>'' THEN
  SELECT * INTO k FROM kit_logistici WHERE codice=m.kit_codice FOR UPDATE;
  IF FOUND THEN
   old_state:=k.stato;
   UPDATE kit_logistici SET stato=next_state,missione_id=m.id,corriere_id=m.corriere_id,struttura_id=m.struttura_id,updated_at=now() WHERE id=k.id;
   INSERT INTO movimenti_kit_corrieri(kit_id,missione_id,corriere_id,struttura_id,movimento,stato_precedente,stato_nuovo,utente)
   VALUES(k.id,m.id,m.corriere_id,m.struttura_id,CASE WHEN p_action='STAMP' THEN 'TIMBRATURA_ARRIVO' ELSE m.tipo END,old_state,next_state,u.username);
  END IF;
 END IF;
 RETURN jsonb_build_object('ok',true);
END $$;
REVOKE ALL ON FUNCTION public.orthoflow_mobile_mission(bigint,bigint,text,jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.orthoflow_mobile_mission(bigint,bigint,text,jsonb) TO service_role;

CREATE OR REPLACE FUNCTION public.orthoflow_mobile_scarico(p_user_id bigint,p_request_id text,p_header jsonb,p_rows jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path = public AS $$
DECLARE u utenti_app%ROWTYPE; existing jsonb; result jsonb; manager boolean; r jsonb;
BEGIN
 SELECT * INTO u FROM utenti_app WHERE id=p_user_id FOR SHARE;
 IF NOT FOUND OR NOT u.attivo OR u.stato_accesso<>'APPROVATO' THEN RAISE EXCEPTION 'MOBILE_UNAUTHORIZED'; END IF;
 manager:=u.ruolo='Admin' OR 'DIREZIONE'=ANY(u.permessi);
 IF NOT manager AND NOT ('AGENTE'=ANY(u.permessi) OR 'OPERATIVITA'=ANY(u.permessi)) THEN RAISE EXCEPTION 'MOBILE_UNAUTHORIZED'; END IF;
 IF p_request_id !~ '^[a-zA-Z0-9-]{16,80}$' THEN RAISE EXCEPTION 'MOBILE_INVALID_REQUEST'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('orthoflow-mobile:'||p_user_id||':'||p_request_id,0));
 SELECT o.result INTO existing FROM orthoflow_mobile_operations o WHERE user_id=p_user_id AND request_id=p_request_id;
 IF FOUND THEN RETURN existing; END IF;
 IF 'AGENTE'=ANY(u.permessi) AND NOT manager AND NOT EXISTS(
  SELECT 1 FROM clienti WHERE codice_cliente=p_header->>'codice_cliente' AND agente=u.agente_nome AND coalesce(trim(u.agente_nome),'')<>''
 ) THEN RAISE EXCEPTION 'MOBILE_CUSTOMER_UNAVAILABLE'; END IF;
 IF jsonb_array_length(p_rows) NOT BETWEEN 1 AND 300 THEN RAISE EXCEPTION 'MOBILE_INVALID_ROWS'; END IF;
 FOR r IN SELECT * FROM jsonb_array_elements(p_rows) LOOP
  IF r->>'prezzo_source'='MANUALE' AND NOT manager AND NOT ('AMMINISTRAZIONE'=ANY(u.permessi)) THEN RAISE EXCEPTION 'MOBILE_PRICE_FORBIDDEN'; END IF;
 END LOOP;
 p_header:=p_header||jsonb_build_object('agente',coalesce(nullif(trim(u.agente_nome),''),u.username));
 result:=crea_intervento_scarico_ai_flessibile(p_header,p_rows,u.username);
 INSERT INTO orthoflow_mobile_operations(user_id,request_id,intervento_id,result)
 VALUES(p_user_id,p_request_id,(result->>'intervento_id')::bigint,result);
 -- Same reintegration records as desktop, part of the transaction.
 INSERT INTO reintegri_kit(kit_id,riga_intervento_id,codice,lotto_consumato,quantita_richiesta,stato,utente)
 SELECT k.id,ri.id,ri.codice,ri.lotto,ri.quantita,'DA_REINTEGRARE',u.username
 FROM righe_intervento ri JOIN kit_logistici k ON k.codice_magazzino=p_header->>'magazzino_scarico'
 WHERE ri.intervento_id=(result->>'intervento_id')::bigint AND coalesce(ri.origine,'')<>'CONTO DEPOSITO STRUTTURA'
 AND (SELECT count(*) FROM kit_logistici WHERE codice_magazzino=p_header->>'magazzino_scarico')=1
 AND NOT EXISTS(SELECT 1 FROM reintegri_kit re WHERE re.kit_id=k.id AND re.riga_intervento_id=ri.id);
 RETURN result;
END $$;
REVOKE ALL ON FUNCTION public.orthoflow_mobile_scarico(bigint,text,jsonb,jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.orthoflow_mobile_scarico(bigint,text,jsonb,jsonb) TO service_role;
COMMIT;
