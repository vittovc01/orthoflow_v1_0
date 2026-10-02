-- Materiale struttura Malzoni (9010013): ricavi e ordini inclusi, nessuno scarico di giacenza.
-- Mantiene firma e privilegi della RPC esistente; usa origine per salvare la proprietà.
CREATE OR REPLACE FUNCTION public.crea_intervento_scarico_ai_flessibile(p_header jsonb, p_rows jsonb, p_utente text DEFAULT NULL::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare v_id bigint; r jsonb; v_q numeric; v_av numeric; v_gid bigint; v_total numeric:=0; v_count int:=0; v_structure boolean; v_no_lot boolean; v_remaining numeric; v_take numeric; g record;
begin
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
  if v_no_lot then
   select coalesce(sum(locked.quantita),0) into v_av from (
    select quantita from giacenze
    where codice_magazzino=p_header->>'magazzino_scarico'
    and regexp_replace(upper(codice),'[^A-Z0-9]','','g')=regexp_replace(upper(r->>'codice'),'[^A-Z0-9]','','g')
    and coalesce(trim(lotto),'')='' and quantita>0
    order by id for update) locked;
  else
  select id,quantita into v_gid,v_av from giacenze
   where codice_magazzino=p_header->>'magazzino_scarico'
   and regexp_replace(upper(codice),'[^A-Z0-9]','','g')=regexp_replace(upper(r->>'codice'),'[^A-Z0-9]','','g')
   and upper(trim(lotto))=upper(trim(r->>'lotto')) and quantita>0 order by id limit 1 for update;
  end if;
  if coalesce(v_av,0)>=v_q then
   if v_no_lot then
    v_remaining:=v_q;
    for g in select id,quantita from giacenze
     where codice_magazzino=p_header->>'magazzino_scarico'
     and regexp_replace(upper(codice),'[^A-Z0-9]','','g')=regexp_replace(upper(r->>'codice'),'[^A-Z0-9]','','g')
     and coalesce(trim(lotto),'')='' and quantita>0 order by id for update loop
     exit when v_remaining<=0;
     v_take:=least(v_remaining,g.quantita);
     update giacenze set quantita=quantita-v_take,updated_at=now() where id=g.id;
     v_remaining:=v_remaining-v_take;
    end loop;
   else
    update giacenze set quantita=quantita-v_q,updated_at=now() where id=v_gid;
   end if;
   insert into movimenti_magazzino(data_movimento,tipo_movimento,codice_magazzino,codice,descrizione,lotto,scadenza,quantita,origine,riferimento_tipo,riferimento_id,note,utente)
   values(now(),'SCARICO',p_header->>'magazzino_scarico',r->>'codice',r->>'descrizione',r->>'lotto',nullif(r->>'scadenza','')::date,-v_q,'SCARICO SALA AI','INTERVENTO',v_id::text,'Scarico sala AI flessibile',p_utente);
  else
   insert into anomalie_giacenza(codice,lotto,quantita_richiesta,quantita_disponibile,magazzino,intervento_id,stato,motivo,creato_da)
   values(r->>'codice',r->>'lotto',v_q,coalesce(v_av,0),p_header->>'magazzino_scarico',v_id,'DA_VERIFICARE','GIACENZA_INSUFFICIENTE',p_utente);
  end if;
  end if;
  insert into righe_intervento(intervento_id,codice,descrizione,lotto,scadenza,quantita,produttore,validazione,prezzo,totale,valore,prezzo_source,origine)
  values(v_id,r->>'codice',r->>'descrizione',r->>'lotto',nullif(r->>'scadenza','')::date,v_q,r->>'produttore',case when v_no_lot then concat_ws(' · ',nullif(r->>'validazione',''),'Non sterile senza lotto') else r->>'validazione' end,coalesce((r->>'prezzo')::numeric,0),coalesce((r->>'prezzo')::numeric,0)*v_q,coalesce((r->>'prezzo')::numeric,0)*v_q,r->>'prezzo_source',case when v_structure then 'CONTO DEPOSITO STRUTTURA' else 'CONTO DEPOSITO' end);
  v_total:=v_total+coalesce((r->>'prezzo')::numeric,0)*v_q; v_count:=v_count+1;
 end loop;
 return jsonb_build_object('intervento_id',v_id,'righe',v_count,'totale',v_total);
end $function$
;
