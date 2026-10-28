-- Transactional, idempotent imports; no intervention or inventory mutations.
alter table public.chiusure_mensili_johnson add column if not exists source_fingerprint text;
create unique index if not exists ux_jj_closure_fingerprint
 on public.chiusure_mensili_johnson(source_fingerprint) where source_fingerprint is not null;

create or replace function public.importa_chiusura_jj(
 p_divisione text, p_mese date, p_nome_file text, p_fingerprint text, p_righe jsonb)
returns jsonb language plpgsql security invoker set search_path=public as $$
declare cid bigint; existing public.chiusure_mensili_johnson%rowtype;
 r jsonb; n integer; tot numeric:=0; nis numeric:=0; inv numeric:=0;
begin
 if p_divisione is null or p_divisione not in ('TRAUMA','PROTESICA') or p_mese is null
 or coalesce(p_fingerprint,'') !~ '^[a-f0-9]{64}$'
 or coalesce(jsonb_typeof(p_righe),'')<>'array' then
  raise exception 'Divisione, mese o dati sorgente non validi';
 end if;
 n:=jsonb_array_length(p_righe);
 if n=0 then raise exception 'Nessuna riga da importare'; end if;
 perform pg_advisory_xact_lock(hashtext('jj-closure-'||p_fingerprint));
 select * into existing from public.chiusure_mensili_johnson where source_fingerprint=p_fingerprint;
 if found then
  if existing.divisione<>p_divisione or existing.mese<>date_trunc('month',p_mese)::date then
   raise exception 'File già importato con divisione o mese differenti';
  end if;
  return jsonb_build_object('id',existing.id,'righe',existing.righe_totali,'gia_presente',true);
 end if;
 for r in select value from jsonb_array_elements(p_righe) loop
  if coalesce(btrim(r->>'codice'),'')='' or jsonb_typeof(r->'raw_data') is distinct from 'object' then
   raise exception 'Riga priva di codice o provenienza';
  end if;
  if r ? 'chiusura_id' or r ? 'id' then raise exception 'Identificatori di riga non ammessi'; end if;
  if coalesce(r->'raw_data'->>'Product[P. Bravo Franchise]','')<>''
     and upper(r->'raw_data'->>'Product[P. Bravo Franchise]')<>p_divisione then
    raise exception 'Divisione sorgente discordante';
  end if;
  tot:=tot+coalesce((r->>'totale_riga')::numeric,0);
  nis:=nis+coalesce((r->>'nis')::numeric,0);
  inv:=inv+coalesce((r->>'invoiced_sales')::numeric,0);
 end loop;
 if tot::text in ('NaN','Infinity','-Infinity') or nis::text in ('NaN','Infinity','-Infinity')
 or inv::text in ('NaN','Infinity','-Infinity') then raise exception 'Importi non validi'; end if;
 insert into public.chiusure_mensili_johnson(mese,divisione,nome_file,source_fingerprint,
  importo_totale_jj,nis_totale,invoiced_sales_totale,righe_totali,stato)
 values(date_trunc('month',p_mese)::date,p_divisione,p_nome_file,p_fingerprint,tot,nis,inv,n,'DA_VERIFICARE') returning id into cid;
 insert into public.righe_chiusura_johnson(chiusura_id,codice,numero_ordine,riferimento_cliente,lotto,
 quantita,prezzo_unitario,totale_riga,raw_data,regione,provincia,bill_to,account_name,famiglia_prodotto,cac,nis,invoiced_sales)
 select cid,codice,numero_ordine,riferimento_cliente,lotto,quantita,prezzo_unitario,totale_riga,raw_data,
 regione,provincia,bill_to,account_name,famiglia_prodotto,cac,x.nis,invoiced_sales
 from jsonb_to_recordset(p_righe) as x(codice text,numero_ordine text,riferimento_cliente text,lotto text,
 quantita numeric,prezzo_unitario numeric,totale_riga numeric,raw_data jsonb,regione text,provincia text,
 bill_to text,account_name text,famiglia_prodotto text,cac text,nis numeric,invoiced_sales numeric);
 return jsonb_build_object('id',cid,'righe',n,'gia_presente',false);
end $$;
revoke all on function public.importa_chiusura_jj(text,date,text,text,jsonb) from public,anon,authenticated;
grant execute on function public.importa_chiusura_jj(text,date,text,text,jsonb) to service_role;
