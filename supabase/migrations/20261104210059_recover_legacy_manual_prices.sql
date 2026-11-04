-- One-time, conservative recovery. All historical rows and existing prices stay unchanged.
CREATE OR REPLACE FUNCTION public.tab_anteprima_prezzi_storici()
RETURNS SETOF jsonb LANGUAGE sql STABLE SECURITY INVOKER SET search_path='' SET jit=off AS $$
 WITH customers AS MATERIALIZED (
   SELECT btrim(codice_cliente) code,coalesce(nullif(btrim(descrizione),''),descrizione_cliente,'') name,
     btrim(regexp_replace(upper(coalesce(nullif(btrim(descrizione),''),descrizione_cliente,'')),'[^A-Z0-9]+',' ','g')) normalized
   FROM public.clienti
 ), raw_targets AS MATERIALIZED (
   SELECT division,btrim(coalesce(payload->>'customer_code','')) code,
     btrim(regexp_replace(upper(coalesce(payload->>'customer','')),'[^A-Z0-9]+',' ','g')) normalized,
     btrim(coalesce(payload->>'cac','')) cac,coalesce(payload->'lines','[]'::jsonb) lines
   FROM public.jj_recon_records WHERE kind='IMPIANTO'
 ), resolved AS MATERIALIZED (
   SELECT division,CASE WHEN t.code<>'' THEN t.code ELSE (
     SELECT min(c.code) FROM customers c WHERE c.normalized=t.normalized AND c.normalized<>''
       HAVING count(DISTINCT c.code)=1) END code,cac,lines FROM raw_targets t
 ), targets AS MATERIALIZED (
   SELECT DISTINCT division,code,cac FROM resolved
 ), target_refs AS MATERIALIZED (
   SELECT DISTINCT division,code,upper(btrim(l->>'ref')) ref,
     regexp_replace(upper(btrim(l->>'ref')),'[^A-Z0-9]','','g') canonical
   FROM resolved CROSS JOIN LATERAL jsonb_array_elements(lines) l
 ), offer_refs AS MATERIALIZED (
   SELECT DISTINCT btrim(c.codice_cliente) code,upper(btrim(h.linea)) division,
     upper(btrim(p.codice)) ref,regexp_replace(upper(btrim(p.codice)),'[^A-Z0-9]','','g') canonical,
     h.data_inizio dal,h.data_fine al,p.prezzo
   FROM public.offerte_prezzi p JOIN public.offerte_header h ON h.id=p.offerta_id
     JOIN public.offerte_clienti c ON c.offerta_id=h.id
   WHERE upper(coalesce(nullif(btrim(h.stato_record),''),'ATTIVO')) IN ('ATTIVO','ACTIVE')
     AND (h.data_inizio IS NULL OR h.data_fine IS NULL OR h.data_inizio<=h.data_fine)
 ), source AS MATERIALIZED (
   SELECT r.id,btrim(coalesce(i.codice_cliente,'')) code,upper(btrim(coalesce(i.linea,''))) division,
     upper(btrim(coalesce(r.codice,''))) ref,
     regexp_replace(upper(btrim(coalesce(r.codice,''))),'[^A-Z0-9]','','g') canonical,extract(year FROM i.data_intervento)::int anno,
     r.prezzo,r.prezzo_source,i.data_intervento,r.prezzo_verificato_at,r.prezzo_verificato_da,
     (r.prezzo IS NOT NULL AND r.prezzo::text NOT IN ('NaN','Infinity','-Infinity') AND
       ((r.prezzo_source IN ('SCONTO_MERCE','MANUALE_MEMORIZZATO') AND r.prezzo=0) OR (r.prezzo_source<>'SCONTO_MERCE' AND r.prezzo>0))) valid
   FROM public.righe_intervento r JOIN public.interventi i ON i.id=r.intervento_id
   WHERE r.prezzo_source IN ('MANUALE','MANUALE_DIREZIONE','MANUALE_MEMORIZZATO','SCONTO_MERCE')
     AND upper(coalesce(nullif(btrim(r.stato_record),''),'ATTIVO')) IN ('ATTIVO','ACTIVE')
     AND upper(coalesce(nullif(btrim(i.stato_record),''),'ATTIVO')) IN ('ATTIVO','ACTIVE')
 ), grouped AS MATERIALIZED (
   SELECT code,division,canonical,anno,min(ref) source_ref,count(DISTINCT ref) source_variants,
     min(prezzo) prezzo,count(DISTINCT prezzo) variants,
     bool_and(valid) AND (min(prezzo)<>0 OR bool_or(prezzo_source='SCONTO_MERCE')) valid,count(*) source_count,
     jsonb_agg(jsonb_build_object('riga_id',id,'ref_originale',ref,'prezzo',prezzo::text,'fonte',prezzo_source,
       'data_intervento',data_intervento,'verificato_da',prezzo_verificato_da,
       'verificato_il',prezzo_verificato_at) ORDER BY id) provenance,
     jsonb_agg(id ORDER BY id) source_ids
   FROM source GROUP BY code,division,canonical,anno
 ), named AS MATERIALIZED (
   SELECT g.*,CASE WHEN t.variants=1 THEN t.ref WHEN t.variants=0 AND o.variants=1 THEN o.ref ELSE g.source_ref END ref,
     (t.variants>1 OR (t.variants=0 AND o.variants>1) OR (t.variants=0 AND o.variants=0 AND g.source_variants>1)) ref_ambiguous
   FROM grouped g CROSS JOIN LATERAL (
     SELECT count(DISTINCT r.ref) variants,min(r.ref) ref FROM target_refs r
       WHERE r.code=g.code AND r.division=g.division AND r.canonical=g.canonical AND r.ref<>''
   ) t CROSS JOIN LATERAL (
     SELECT count(DISTINCT r.ref) variants,min(r.ref) ref FROM offer_refs r
       WHERE r.code=g.code AND r.division=g.division AND r.canonical=g.canonical AND r.ref<>''
         AND (r.dal IS NULL OR r.dal<=make_date(g.anno,12,31)) AND (r.al IS NULL OR r.al>=make_date(g.anno,1,1))
   ) o
 ), scoped AS (
   SELECT g.*,s.cacs,s.presidi FROM named g CROSS JOIN LATERAL (
     SELECT coalesce(array_agg(DISTINCT t.cac) FILTER(WHERE t.code IS NOT NULL),ARRAY['']::text[]) cacs,
       count(DISTINCT nullif(t.cac,'')) presidi FROM targets t WHERE t.code=g.code AND t.division=g.division
   ) s
 ), expanded AS (
   SELECT g.*,cac,make_date(anno,1,1) dal,make_date(anno,12,31) al,
     md5(jsonb_build_array(code,division,ref,anno,cac)::text) recovery_key
   FROM scoped g CROSS JOIN LATERAL unnest(g.cacs) cac
 ), classified AS (
   SELECT g.*,c.name structure,
     CASE
       WHEN EXISTS(SELECT 1 FROM public.tab_prezzi_verificati v WHERE v.codice_cliente=g.code AND v.cac=g.cac
         AND v.linea=g.division AND regexp_replace(v.ref,'[^A-Z0-9]','','g')=regexp_replace(g.ref,'[^A-Z0-9]','','g')
         AND v.dal<=g.al AND v.al>=g.dal AND v.nota LIKE 'RECUPERO_STORICO_V1|'||g.recovery_key||'|%') THEN 'GIA_RECUPERATO'
       WHEN EXISTS(SELECT 1 FROM public.tab_prezzi_verificati v WHERE v.codice_cliente=g.code AND v.cac=g.cac
         AND v.linea=g.division AND regexp_replace(v.ref,'[^A-Z0-9]','','g')=regexp_replace(g.ref,'[^A-Z0-9]','','g')
         AND v.dal<=g.al AND v.al>=g.dal) THEN 'GIA_PRESENTE'
       WHEN c.code IS NULL OR g.code='' OR g.division NOT IN ('TRAUMA','PROTESICA') OR g.anno IS NULL
         OR g.anno NOT BETWEEN 2000 AND 2100 OR g.ref !~ '^[A-Z0-9][A-Z0-9._/-]*$' OR NOT g.valid THEN 'DA_VERIFICARE_DATI'
       WHEN g.variants<>1 THEN 'DA_VERIFICARE_PREZZI_STORICI'
       WHEN g.presidi>1 THEN 'DA_VERIFICARE_PRESIDIO'
       WHEN g.ref_ambiguous THEN 'DA_VERIFICARE_REF'
       WHEN EXISTS(SELECT 1 FROM offer_refs p WHERE p.code=g.code AND p.division=g.division
         AND p.canonical=g.canonical AND (p.dal IS NULL OR p.dal<=g.al) AND (p.al IS NULL OR p.al>=g.dal)
         AND p.prezzo IS NOT NULL AND p.prezzo>=0 AND p.prezzo::text NOT IN ('NaN','Infinity','-Infinity')
         AND p.prezzo<>g.prezzo) THEN 'DA_VERIFICARE_OFFERTA'
       ELSE 'RECUPERABILE'
     END status
   FROM expanded g LEFT JOIN customers c ON c.code=g.code
 )
 SELECT jsonb_build_object('chiave',recovery_key,'codice_cliente',code,'struttura',coalesce(structure,code),
   'linea',division,'cac',cac,'ref',ref,'anno',anno,'dal',dal,'al',al,'prezzo',prezzo::text,
   'stato',status,'righe_origine',source_count,'origine_ids',source_ids,'provenienza',provenance,
   'nota_validita','Anno degli interventi storici; validità contrattuale originaria non disponibile')
 FROM classified ORDER BY code,division,ref,anno,cac;
$$;
REVOKE ALL ON FUNCTION public.tab_anteprima_prezzi_storici() FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.tab_anteprima_prezzi_storici() TO service_role;

CREATE OR REPLACE FUNCTION public.tab_recupera_prezzi_storici(p_applica boolean,p_utente text)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path='' SET jit=off AS $$
DECLARE item jsonb;details jsonb:='[]';answer jsonb;result jsonb;
 recovered integer:=0;present integer:=0;review integer:=0;eligible integer:=0;fingerprint text;
BEGIN
 IF p_applica IS NULL OR nullif(btrim(p_utente),'') IS NULL THEN RAISE EXCEPTION 'Modalità o utente mancanti'; END IF;
 IF p_applica THEN
   PERFORM pg_advisory_xact_lock(hashtextextended('tab_legacy_price_recovery_v1',0));
   -- Briefly serialize writes to the destination, including formatted REF aliases.
   -- SELECTs remain available; the recovery never updates an existing row.
   LOCK TABLE public.tab_prezzi_verificati IN SHARE ROW EXCLUSIVE MODE;
   -- Prevent source corrections while collecting evidence; never write source rows.
   PERFORM r.id FROM public.righe_intervento r JOIN public.interventi i ON i.id=r.intervento_id
     WHERE r.prezzo_source IN ('MANUALE','MANUALE_DIREZIONE','MANUALE_MEMORIZZATO','SCONTO_MERCE')
     ORDER BY r.id FOR SHARE OF r,i;
 END IF;
 FOR item IN SELECT * FROM public.tab_anteprima_prezzi_storici() LOOP
   IF item->>'stato'='RECUPERABILE' THEN
     eligible:=eligible+1;
     IF p_applica THEN
       -- Same scope lock used by the normal price editor. Recheck after locking.
       PERFORM pg_advisory_xact_lock(hashtextextended((item->>'codice_cliente')||'|'||(item->>'cac')||'|'||
         (item->>'linea')||'|'||(item->>'ref'),0));
       IF EXISTS(SELECT 1 FROM public.tab_prezzi_verificati v WHERE v.codice_cliente=item->>'codice_cliente'
         AND v.cac=item->>'cac' AND v.linea=item->>'linea'
         AND regexp_replace(v.ref,'[^A-Z0-9]','','g')=regexp_replace(item->>'ref','[^A-Z0-9]','','g')
         AND v.dal<=(item->>'al')::date AND v.al>=(item->>'dal')::date) THEN
         item:=item||jsonb_build_object('stato','GIA_PRESENTE');
       ELSE
         result:=public.tab_salva_prezzo_verificato(item->>'codice_cliente',item->>'cac',item->>'linea',item->>'ref',
           (item->>'prezzo')::numeric,(item->>'dal')::date,(item->>'al')::date,p_utente,
           'RECUPERO_STORICO_V1|'||(item->>'chiave')||'| Righe '||(item->'origine_ids')::text||
           '. Prezzo manuale preesistente. Anno storico; validità contrattuale originaria non disponibile.',
           (item->>'prezzo')::numeric=0);
         recovered:=recovered+1;
         item:=item||jsonb_build_object('stato','RECUPERATO','prezzo_id',result->'id');
       END IF;
     END IF;
   END IF;
   IF item->>'stato' IN ('GIA_PRESENTE','GIA_RECUPERATO') THEN present:=present+1; END IF;
   IF item->>'stato' LIKE 'DA_VERIFICARE_%' THEN review:=review+1; END IF;
   details:=details||jsonb_build_array(item);
 END LOOP;
 fingerprint:=md5((SELECT coalesce(jsonb_agg(jsonb_build_array(e->>'chiave',e->'provenienza') ORDER BY e->>'chiave'),'[]')::text
   FROM jsonb_array_elements(details) e));
 answer:=jsonb_build_object('applicato',p_applica,'prezzi_recuperati',recovered,'recuperabili',eligible,
   'gia_presenti',present,'da_verificare',review,'dettaglio',details,'fingerprint',fingerprint,'eseguito_il',now(),
   'criterio_validita','Anno degli interventi di origine, senza estensione agli anni successivi');
 IF p_applica AND (recovered>0 OR NOT EXISTS(SELECT 1 FROM public.audit_log
   WHERE azione='RECUPERO_PREZZI_STORICI' AND riferimento='legacy_manual_v1:'||fingerprint)) THEN
   INSERT INTO public.audit_log(utente,azione,tabella,riferimento,dettagli)
   VALUES(p_utente,'RECUPERO_PREZZI_STORICI','tab_prezzi_verificati','legacy_manual_v1:'||fingerprint,answer::text);
 END IF;
 RETURN answer;
END $$;
REVOKE ALL ON FUNCTION public.tab_recupera_prezzi_storici(boolean,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.tab_recupera_prezzi_storici(boolean,text) TO service_role;
