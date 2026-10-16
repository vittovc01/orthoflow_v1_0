-- New isolated RPC; deploy before UI activation. No historical stock repair.
-- Materiale struttura Malzoni (9010013): ricavi e ordini inclusi, nessuno scarico di giacenza.
-- Mantiene firma e privilegi della RPC esistente; usa origine per salvare la proprietà.
-- Transactional idempotency for the v2 review. No images or patient names.
CREATE TABLE IF NOT EXISTS public.scarico_ai_requests (
 request_id uuid PRIMARY KEY, payload_hash text NOT NULL,
 business_key text UNIQUE, source_key text UNIQUE,
 actor text NOT NULL, response jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.scarico_ai_requests ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.scarico_ai_requests FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT ON public.scarico_ai_requests TO service_role;

CREATE OR REPLACE FUNCTION public.crea_intervento_scarico_ai_verificato(p_header jsonb, p_rows jsonb, p_utente text DEFAULT NULL::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY INVOKER
 SET search_path TO 'public'
AS $function$
declare v_id bigint; r jsonb; v_q numeric; v_av numeric; v_gid bigint; v_total numeric:=0; v_count int:=0; v_anomalies int:=0; v_reason text; v_structure boolean; v_no_lot boolean; v_remaining numeric; v_take numeric; g record; v_simple boolean; v_label text; v_request uuid; v_hash text; v_business text; v_source text; v_lock text; v_existing public.scarico_ai_requests%rowtype; v_response jsonb; v_previous bigint;
begin
 v_simple:=coalesce(p_header->>'review_contract_version','1')='2';
 if not coalesce((p_header->>'count_verified')::boolean,false)
    or jsonb_typeof(p_rows) is distinct from 'array' or jsonb_array_length(p_rows)=0
    or coalesce((p_header->>'physical_label_count')::int,0)<=0 then
   raise exception 'ETICHETTE_NON_VERIFICATE';
 end if;
 if jsonb_typeof(p_header->'included_label_ids') is distinct from 'array' then
   raise exception 'IDENTITA_FISICHE_MANCANTI';
 end if;
 for r in select * from jsonb_array_elements(p_rows) loop
   v_label:=coalesce(nullif(trim(r->>'codice'),''),'REF mancante') || ', lotto ' || coalesce(nullif(trim(r->>'lotto'),''),'mancante');
   if coalesce(r->>'quantita','') !~ '^[0-9]+(\.[0-9]+)?$' then
     raise exception '%: quantità non valida o conferma mancante (ETICHETTA_QUANTITA_NON_VERIFICATA)',v_label;
   end if;
   if not coalesce((r->>'verificata')::boolean,false)
      or jsonb_typeof(r->'label_ids') is distinct from 'array'
      or jsonb_array_length(r->'label_ids')=0
      or nullif(r->>'quantita','')::numeric is null
      or (r->>'quantita')::numeric::text in ('NaN','Infinity','-Infinity')
      or (r->>'quantita')::numeric<=0
      or trunc((r->>'quantita')::numeric)<>(r->>'quantita')::numeric
      or (not v_simple and (r->>'quantita')::numeric <> jsonb_array_length(r->'label_ids')) then
     raise exception '%: quantità non valida o conferma mancante (ETICHETTA_QUANTITA_NON_VERIFICATA)',v_label;
   end if;
   if v_simple then
     if lower(coalesce(trim(r->>'codice'),'')) in ('','nan','null','none','<na>') then
       raise exception '%: REF mancante',v_label;
     end if;
     if lower(coalesce(trim(r->>'lotto'),'')) in ('','nan','null','none','<na>') then
       raise exception '%: lotto mancante',v_label;
     end if;
     if length(r->>'lotto')>20 or r->>'lotto' ~ '[[:cntrl:]]' then
       raise exception '%: lotto non valido',v_label;
     end if;
     if coalesce(r->>'scadenza','') !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' then
       raise exception '%: scadenza mancante o non valida (AAAA-MM-GG)',v_label;
     end if;
     begin
       perform (r->>'scadenza')::date;
     exception when invalid_datetime_format or datetime_field_overflow then
       raise exception '%: scadenza non valida',v_label;
     end;
   end if;
   if v_simple then
     -- Quantity is editable; keep its server-side trace tied to real review rows.
     if jsonb_typeof(p_header->'label_manifest') is distinct from 'array' then
       raise exception '%: revisione delle righe mancante',v_label;
     end if;
     if (select count(distinct m->>'label_id') from jsonb_array_elements(p_header->'label_manifest') m
          where m->>'label_id' in (select jsonb_array_elements_text(r->'label_ids')))
           <>jsonb_array_length(r->'label_ids')
        or (select sum((m->>'quantita')::numeric) from jsonb_array_elements(p_header->'label_manifest') m
          where m->>'label_id' in (select jsonb_array_elements_text(r->'label_ids')))
           is distinct from (r->>'quantita')::numeric
        or exists(select 1 from jsonb_array_elements(p_header->'label_manifest') m
          where m->>'label_id' in (select jsonb_array_elements_text(r->'label_ids'))
          and (m->>'codice' is distinct from r->>'codice' or m->>'lotto' is distinct from r->>'lotto'
            or m->>'scadenza' is distinct from r->>'scadenza'
            or coalesce((m->>'esclusa')::boolean,false)
            or coalesce((m->>'quantita')::numeric,0)<=0
            or trunc((m->>'quantita')::numeric)<>(m->>'quantita')::numeric)) then
       raise exception '%: quantità o dati diversi dalla revisione confermata',v_label;
     end if;
     if coalesce(trim(r->>'lotto'),'')='' then raise exception '%: lotto mancante',v_label; end if;
     if nullif(r->>'scadenza','') is null then raise exception '%: scadenza mancante',v_label; end if;
     if coalesce(trim(p_utente),'')='' then raise exception 'Utente della revisione mancante'; end if;
   end if;
   if coalesce(trim(r->>'codice'),'')='' or r->>'codice' ~ '^[0-9]{14}$'
      or r->>'codice' !~ '^[A-Za-z0-9][A-Za-z0-9. /-]*$' then
     raise exception '%: REF non valido (REF_NON_VALIDO)',v_label;
   end if;
   if exists(select 1 from jsonb_array_elements_text(r->'label_ids') as labels(label_id) where label_id is null or trim(label_id)='') then
     raise exception 'IDENTITA_FISICA_VUOTA';
   end if;
   if not v_simple and coalesce((r->>'is_sterile')::boolean,false)
      and r->>'codice' ~ '^([0-9]{2}\.[0-9]{3}\.[0-9]{3}|[0-9]{3}\.[0-9]{3})5?$' then
     raise exception 'REF_STERILE_SENZA_SUFFISSO_VERIFICATO';
   end if;
   if coalesce((r->>'is_sterile')::boolean,false) and coalesce((r->>'senza_lotto')::boolean,false) then
     raise exception 'STERILE_SENZA_LOTTO_NON_AMMESSO';
   end if;
   if not coalesce((r->>'senza_lotto')::boolean,false)
      and nullif(r->>'scadenza','')::date is null then
     raise exception 'SCADENZA_NON_VERIFICATA';
   end if;
 end loop;
 if (select count(*)<>count(distinct label_id) from jsonb_array_elements(p_rows) as rows(item),
       lateral jsonb_array_elements_text(item->'label_ids') as labels(label_id))
    or (select count(*) from jsonb_array_elements(p_rows) as rows(item),
       lateral jsonb_array_elements_text(item->'label_ids') as labels(label_id)) > (p_header->>'physical_label_count')::int
    or (select array_agg(label_id order by label_id) from jsonb_array_elements(p_rows) as rows(item),
       lateral jsonb_array_elements_text(item->'label_ids') as labels(label_id))
       is distinct from (select array_agg(label_id order by label_id) from jsonb_array_elements_text(p_header->'included_label_ids') as labels(label_id)) then
   raise exception 'IDENTITA_FISICHE_DUPLICATE_O_MANCANTI';
 end if;
 if v_simple then
   begin
     v_request:=(p_header->>'request_id')::uuid;
   exception when invalid_text_representation then
     raise exception 'Identificativo della richiesta non valido: riapri la revisione';
   end;
   if v_request is null then raise exception 'Identificativo della richiesta mancante'; end if;
   v_hash:=encode(sha256(convert_to(jsonb_build_object('header',p_header-'request_id','rows',p_rows,'actor',p_utente)::text,'UTF8')),'hex');
   if nullif(trim(p_header->>'cartella_clinica'),'') is not null then
     v_business:=encode(sha256(convert_to(jsonb_build_array(
       upper(trim(coalesce(p_header->>'codice_cliente',''))),
       (p_header->>'data_intervento')::date,
       upper(trim(p_header->>'cartella_clinica')))::text,'UTF8')),'hex');
   end if;
   select string_agg(source,',' order by source) into v_source from (
     select distinct nullif(m->>'source_document','') as source
     from jsonb_array_elements(p_header->'label_manifest') m) sources;
   if v_source is not null then
     v_source:=encode(sha256(convert_to(v_source,'UTF8')),'hex');
   end if;
   if v_business is null and v_source is null then
     raise exception 'Inserire il numero cartella clinica: manca un documento identificabile per proteggere lo scarico dal doppio invio';
   end if;
   -- Stable order prevents deadlocks when request/business/document keys overlap.
   for v_lock in select key from unnest(array['request:'||v_request::text,
       'business:'||v_business,'source:'||v_source]) key where key is not null order by key loop
     perform pg_advisory_xact_lock(hashtextextended(v_lock,0));
   end loop;
   select * into v_existing from public.scarico_ai_requests where request_id=v_request;
   if found then
     if v_existing.payload_hash<>v_hash then
       raise exception 'Richiesta già usata con dati diversi: verificare lo scarico precedente';
     end if;
     return v_existing.response || '{"replayed":true}'::jsonb;
   end if;
   if v_business is not null then
     select id into v_previous from public.interventi
      where upper(trim(coalesce(codice_cliente,'')))=upper(trim(coalesce(p_header->>'codice_cliente','')))
        and data_intervento=(p_header->>'data_intervento')::date
        and upper(trim(coalesce(cartella_clinica,'')))=upper(trim(p_header->>'cartella_clinica'))
      order by id limit 1;
     if found then
       raise exception 'Scarico già registrato: intervento %. Verificare la cartella esistente.',v_previous;
     end if;
   end if;
   select * into v_existing from public.scarico_ai_requests
     where (v_business is not null and business_key=v_business)
        or (v_source is not null and source_key=v_source) limit 1;
   if found then
     raise exception 'Scarico già registrato: intervento %. Non inviare di nuovo la stessa cartella o lo stesso documento.',v_existing.response->>'intervento_id';
   end if;
 end if;
 insert into interventi(data_intervento,codice_cliente,cliente,struttura,cartella_clinica,chirurgo,agente,linea,magazzino_scarico)
 values((p_header->>'data_intervento')::date,p_header->>'codice_cliente',p_header->>'cliente',
        coalesce(nullif(p_header->>'struttura',''),nullif(p_header->>'cliente','')),
        p_header->>'cartella_clinica',p_header->>'chirurgo',p_header->>'agente',p_header->>'linea',p_header->>'magazzino_scarico')
 returning id into v_id;
 for r in select * from jsonb_array_elements(p_rows) loop
  v_q:=coalesce((r->>'quantita')::numeric,0); v_gid:=null; v_av:=0;
  v_structure:=coalesce((r->>'conto_deposito_struttura')::boolean,false);
  v_no_lot:=coalesce((r->>'senza_lotto')::boolean,false);
  if v_q<=0 or coalesce(trim(r->>'codice'),'')='' then raise exception 'CODICE_QUANTITA_NON_VALIDI'; end if;
  if coalesce(trim(r->>'lotto'),'')='' and not v_no_lot then raise exception 'LOTTO_OBBLIGATORIO_O_CONFERMA_NON_STERILE'; end if;
  if v_no_lot and coalesce(trim(r->>'lotto'),'')<>'' then raise exception 'SENZA_LOTTO_CON_LOTTO_PRESENTE'; end if;
  if v_no_lot then r:=r||jsonb_build_object('lotto',''); end if;
  if v_structure and coalesce(p_header->>'codice_cliente','') <> '9010013' then
   raise exception 'CONTO_DEPOSITO_STRUTTURA_SOLO_MALZONI';
  end if;
  if not v_structure then
   -- Lock exact stock identity before checking aggregate availability. Never
   -- substitute a different lot/expiry or partially debit an anomalous row.
   select coalesce(sum(locked.quantita),0) into v_av from (
    select quantita from giacenze
    where codice_magazzino=p_header->>'magazzino_scarico'
    and origine='CONTO DEPOSITO'
    and regexp_replace(upper(codice),'[^A-Z0-9]','','g')=regexp_replace(upper(r->>'codice'),'[^A-Z0-9]','','g')
    and coalesce(trim(lotto),'')=coalesce(trim(r->>'lotto'),'')
    and (v_no_lot or scadenza=nullif(r->>'scadenza','')::date)
    and quantita>0 order by id for update) locked;
   if v_av >= v_q then
    v_remaining:=v_q;
    for g in select id,quantita from giacenze
     where codice_magazzino=p_header->>'magazzino_scarico'
     and origine='CONTO DEPOSITO'
     and regexp_replace(upper(codice),'[^A-Z0-9]','','g')=regexp_replace(upper(r->>'codice'),'[^A-Z0-9]','','g')
     and coalesce(trim(lotto),'')=coalesce(trim(r->>'lotto'),'')
     and (v_no_lot or scadenza=nullif(r->>'scadenza','')::date)
     and quantita>0 order by id for update loop
      exit when v_remaining<=0;
      v_take:=least(v_remaining,g.quantita);
      update giacenze set quantita=quantita-v_take,updated_at=now() where id=g.id;
      v_remaining:=v_remaining-v_take;
    end loop;
    -- Preserve the existing trigger sentinel: stock has already been debited.
    insert into movimenti_magazzino(data_movimento,tipo_movimento,codice_magazzino,codice,descrizione,lotto,scadenza,quantita,origine,riferimento_tipo,riferimento_id,note,utente)
    values(now(),'SCARICO',p_header->>'magazzino_scarico',r->>'codice',r->>'descrizione',r->>'lotto',nullif(r->>'scadenza','')::date,-v_q,'SCARICO SALA AI','INTERVENTO',v_id::text,'Scarico sala AI flessibile',p_utente);
   else
    v_reason:='GIACENZA_INSUFFICIENTE';
    if not exists(select 1 from giacenze where codice_magazzino=p_header->>'magazzino_scarico'
       and origine='CONTO DEPOSITO'
       and regexp_replace(upper(codice),'[^A-Z0-9]','','g')=regexp_replace(upper(r->>'codice'),'[^A-Z0-9]','','g')
       and coalesce(trim(lotto),'')=coalesce(trim(r->>'lotto'),'')) then
      v_reason:='LOTTO_NON_CORRISPONDENTE';
    elsif not v_no_lot and not exists(select 1 from giacenze where codice_magazzino=p_header->>'magazzino_scarico'
       and origine='CONTO DEPOSITO'
       and regexp_replace(upper(codice),'[^A-Z0-9]','','g')=regexp_replace(upper(r->>'codice'),'[^A-Z0-9]','','g')
       and coalesce(trim(lotto),'')=coalesce(trim(r->>'lotto'),'')
       and scadenza=nullif(r->>'scadenza','')::date) then
      v_reason:='SCADENZA_DIVERSA_O_MANCANTE';
    end if;
    insert into anomalie_giacenza(codice,lotto,quantita_richiesta,quantita_disponibile,magazzino,intervento_id,stato,motivo,creato_da)
    values(r->>'codice',r->>'lotto',v_q,v_av,p_header->>'magazzino_scarico',v_id,'DA_VERIFICARE',
      v_reason || ' · Scadenza documento: ' || coalesce(r->>'scadenza','senza scadenza'),p_utente);
    v_anomalies:=v_anomalies+1;
   end if;
  end if;
  insert into righe_intervento(intervento_id,codice,descrizione,lotto,scadenza,quantita,produttore,validazione,prezzo,totale,valore,prezzo_source,origine)
  values(v_id,r->>'codice',r->>'descrizione',r->>'lotto',nullif(r->>'scadenza','')::date,v_q,r->>'produttore',case when v_no_lot then concat_ws(' · ',nullif(r->>'validazione',''),'Non sterile senza lotto') else r->>'validazione' end,coalesce((r->>'prezzo')::numeric,0),coalesce((r->>'prezzo')::numeric,0)*v_q,coalesce((r->>'prezzo')::numeric,0)*v_q,r->>'prezzo_source',case when v_structure then 'CONTO DEPOSITO STRUTTURA' else 'CONTO DEPOSITO' end);
  v_total:=v_total+coalesce((r->>'prezzo')::numeric,0)*v_q; v_count:=v_count+1;
 end loop;
 insert into audit_log(utente,azione,tabella,riferimento,dettagli)
 values(p_utente,'SCARICO_ETICHETTE_VERIFICATE','interventi',v_id::text,
   jsonb_build_object('physical_label_count',p_header->'physical_label_count',
     'label_manifest',p_header->'label_manifest','rows',p_rows,
     'reported_label_count',p_header->'reported_label_count',
     'count_difference',p_header->'count_difference',
     'correction_log',coalesce(p_header->'correction_log','[]'::jsonb))::text);
 v_response:=jsonb_build_object('intervento_id',v_id,'righe',v_count,'totale',v_total,'anomalie',v_anomalies);
 if v_simple then
   insert into public.scarico_ai_requests(request_id,payload_hash,business_key,source_key,actor,response)
   values(v_request,v_hash,v_business,v_source,p_utente,v_response);
 end if;
 return v_response;
end $function$
;

REVOKE ALL ON FUNCTION public.crea_intervento_scarico_ai_verificato(jsonb,jsonb,text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.crea_intervento_scarico_ai_verificato(jsonb,jsonb,text) TO service_role;

-- Dedicated endpoint: callers cannot select the weaker legacy contract.
CREATE OR REPLACE FUNCTION public.crea_intervento_scarico_ai_verificato_v2(
 p_header jsonb,p_rows jsonb,p_utente text DEFAULT NULL
) RETURNS jsonb LANGUAGE sql SECURITY INVOKER SET search_path TO 'public' AS $$
 SELECT public.crea_intervento_scarico_ai_verificato(
   coalesce(p_header,'{}'::jsonb)||'{"review_contract_version":2}'::jsonb,p_rows,p_utente);
$$;
REVOKE ALL ON FUNCTION public.crea_intervento_scarico_ai_verificato_v2(jsonb,jsonb,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.crea_intervento_scarico_ai_verificato_v2(jsonb,jsonb,text) TO service_role;
