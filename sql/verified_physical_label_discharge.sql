-- New isolated RPC; deploy before UI activation. No historical stock repair.
-- Materiale struttura Malzoni (9010013): ricavi e ordini inclusi, nessuno scarico di giacenza.
-- Mantiene firma e privilegi della RPC esistente; usa origine per salvare la proprietà.
CREATE OR REPLACE FUNCTION public.crea_intervento_scarico_ai_verificato(p_header jsonb, p_rows jsonb, p_utente text DEFAULT NULL::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY INVOKER
 SET search_path TO 'public'
AS $function$
declare v_id bigint; r jsonb; v_q numeric; v_av numeric; v_gid bigint; v_total numeric:=0; v_count int:=0; v_structure boolean; v_no_lot boolean; v_remaining numeric; v_take numeric; g record;
begin
 if not coalesce((p_header->>'count_verified')::boolean,false)
    or jsonb_typeof(p_rows) is distinct from 'array' or jsonb_array_length(p_rows)=0
    or coalesce((p_header->>'physical_label_count')::int,0)<=0 then
   raise exception 'ETICHETTE_NON_VERIFICATE';
 end if;
 if jsonb_typeof(p_header->'included_label_ids') is distinct from 'array' then
   raise exception 'IDENTITA_FISICHE_MANCANTI';
 end if;
 for r in select * from jsonb_array_elements(p_rows) loop
   if not coalesce((r->>'verificata')::boolean,false)
      or jsonb_typeof(r->'label_ids') is distinct from 'array'
      or jsonb_array_length(r->'label_ids')=0
      or (r->>'quantita')::numeric <> jsonb_array_length(r->'label_ids') then
     raise exception 'ETICHETTA_QUANTITA_NON_VERIFICATA';
   end if;
   if coalesce(trim(r->>'codice'),'')='' or r->>'codice' ~ '^[0-9]{14}$'
      or r->>'codice' !~ '^[A-Za-z0-9][A-Za-z0-9. /-]*$' then
     raise exception 'REF_NON_VALIDO';
   end if;
   if exists(select 1 from jsonb_array_elements_text(r->'label_ids') as labels(label_id) where label_id is null or trim(label_id)='') then
     raise exception 'IDENTITA_FISICA_VUOTA';
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
   if v_remaining>0 then raise exception 'GIACENZA_INSUFFICIENTE_O_SCADENZA_DIVERSA'; end if;
   insert into movimenti_magazzino(data_movimento,tipo_movimento,codice_magazzino,codice,descrizione,lotto,scadenza,quantita,origine,riferimento_tipo,riferimento_id,note,utente)
   values(now(),'SCARICO',p_header->>'magazzino_scarico',r->>'codice',r->>'descrizione',r->>'lotto',nullif(r->>'scadenza','')::date,-v_q,'SCARICO SALA AI','INTERVENTO',v_id::text,'Scarico etichette fisiche verificate',p_utente);
  end if;
  insert into righe_intervento(intervento_id,codice,descrizione,lotto,scadenza,quantita,produttore,validazione,prezzo,totale,valore,prezzo_source,origine)
  values(v_id,r->>'codice',r->>'descrizione',r->>'lotto',nullif(r->>'scadenza','')::date,v_q,r->>'produttore',case when v_no_lot then concat_ws(' · ',nullif(r->>'validazione',''),'Non sterile senza lotto') else r->>'validazione' end,coalesce((r->>'prezzo')::numeric,0),coalesce((r->>'prezzo')::numeric,0)*v_q,coalesce((r->>'prezzo')::numeric,0)*v_q,r->>'prezzo_source',case when v_structure then 'CONTO DEPOSITO STRUTTURA' else 'CONTO DEPOSITO' end);
  v_total:=v_total+coalesce((r->>'prezzo')::numeric,0)*v_q; v_count:=v_count+1;
 end loop;
 return jsonb_build_object('intervento_id',v_id,'righe',v_count,'totale',v_total);
end $function$
;

REVOKE ALL ON FUNCTION public.crea_intervento_scarico_ai_verificato(jsonb,jsonb,text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.crea_intervento_scarico_ai_verificato(jsonb,jsonb,text) TO service_role;
