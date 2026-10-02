CREATE OR REPLACE FUNCTION public.elimina_intervento_completo(p_intervento_id bigint, p_utente text)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path=public
AS $fn$
DECLARE v_header jsonb; v_rows jsonb; v_docs jsonb; v_count integer;
BEGIN
 SELECT to_jsonb(i) INTO v_header FROM interventi i WHERE i.id=p_intervento_id FOR UPDATE;
 IF v_header IS NULL THEN RAISE EXCEPTION 'INTERVENTO_NON_PRESENTE'; END IF;
 -- Lock children before taking an audit snapshot and deleting them.
 PERFORM 1 FROM righe_intervento WHERE intervento_id=p_intervento_id FOR UPDATE;
 PERFORM 1 FROM documenti_impianto WHERE intervento_id=p_intervento_id::text FOR UPDATE;
 SELECT coalesce(jsonb_agg(to_jsonb(r)),'[]'::jsonb) INTO v_rows FROM righe_intervento r WHERE intervento_id=p_intervento_id;
 SELECT coalesce(jsonb_agg(to_jsonb(d)),'[]'::jsonb) INTO v_docs FROM documenti_impianto d WHERE intervento_id=p_intervento_id::text;
 v_count=jsonb_array_length(v_rows);
 INSERT INTO audit_log(utente,azione,tabella,riferimento,dettagli)
 VALUES(p_utente,'ELIMINAZIONE_COMPLETA','interventi',p_intervento_id::text,
 jsonb_build_object('intervento',v_header,'righe',v_rows,'documenti',v_docs,
 'giacenze','invariate: cancellazione amministrativa, non storno materiale')::text);
 -- Keep completed replenishments and commercial documents as historical records.
 DELETE FROM reintegri_kit WHERE riga_intervento_id IN
 (SELECT id FROM righe_intervento WHERE intervento_id=p_intervento_id)
 AND coalesce(quantita_reintegrata,0)=0 AND ddt_riga_id IS NULL;
 DELETE FROM anomalie_giacenza WHERE intervento_id=p_intervento_id;
 DELETE FROM documenti_impianto WHERE intervento_id=p_intervento_id::text;
 DELETE FROM righe_intervento WHERE intervento_id=p_intervento_id;
 DELETE FROM interventi WHERE id=p_intervento_id;
 RETURN jsonb_build_object('intervento_id',p_intervento_id,'righe',v_count,'documenti',v_docs);
END
$fn$;
REVOKE ALL ON FUNCTION public.elimina_intervento_completo(bigint,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.elimina_intervento_completo(bigint,text) TO service_role;
