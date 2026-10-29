-- Separate accounting ledger. Never writes interventions or warehouse movements.
create table if not exists public.jj_recon_records(
 id bigint generated always as identity primary key,
 kind text not null check(kind in ('IMPIANTO','ORDINE','CHIUSURA')),
 division text not null check(division in ('TRAUMA','PROTESICA')),
 source_key text not null,payload jsonb not null,pending_payload jsonb,
 source_file text not null,updated_at timestamptz not null default now(),closed_at timestamptz,
 unique(kind,division,source_key));
create table if not exists public.jj_recon_links(
 id bigint generated always as identity primary key,
 closure_id bigint not null references public.jj_recon_records(id),closure_line text not null,
 order_id bigint not null references public.jj_recon_records(id),order_line text not null,
 implant_id bigint not null references public.jj_recon_records(id),implant_line text not null,
 quantity integer not null check(quantity>0),method text not null,
 actor text not null,created_at timestamptz not null default now(),revoked_at timestamptz);
create unique index if not exists ux_jj_recon_active on public.jj_recon_links
 (closure_id,closure_line,order_id,order_line,implant_id,implant_line) where revoked_at is null;
create index if not exists ix_jj_recon_order on public.jj_recon_links(order_id) where revoked_at is null;
create index if not exists ix_jj_recon_implant on public.jj_recon_links(implant_id) where revoked_at is null;
create table if not exists public.jj_recon_audit(
 id bigint generated always as identity primary key,record_id bigint references public.jj_recon_records(id),
 action text not null,before_value jsonb,after_value jsonb,actor text not null,created_at timestamptz not null default now());
alter table public.jj_recon_records enable row level security;
alter table public.jj_recon_links enable row level security;
alter table public.jj_recon_audit enable row level security;
revoke all on public.jj_recon_records,public.jj_recon_links,public.jj_recon_audit from anon,authenticated;
grant select,insert,update on public.jj_recon_records,public.jj_recon_links,public.jj_recon_audit to service_role;
grant usage,select on sequence public.jj_recon_records_id_seq,public.jj_recon_links_id_seq,public.jj_recon_audit_id_seq to service_role;

create or replace function public.jj_validate_payload(p_kind text,p_payload jsonb)
returns void language plpgsql security invoker set search_path=public as $$
declare l jsonb;q numeric; keys text[]:='{}';
begin
 if p_kind='CHIUSURA' and coalesce(p_payload->>'month','') !~ '^[0-9]{4}-(0[1-9]|1[0-2])$' then raise exception 'Mese chiusura non valido'; end if;
 if jsonb_typeof(p_payload) is distinct from 'object' or jsonb_typeof(p_payload->'lines') is distinct from 'array'
 or jsonb_array_length(p_payload->'lines')=0 then raise exception 'Documento privo di righe'; end if;
 for l in select value from jsonb_array_elements(p_payload->'lines') loop
  if coalesce(l->>'key','')='' or (l->>'key')=any(keys) or coalesce(l->>'ref','') !~ '^[A-Z0-9][A-Z0-9._/-]*$' then raise exception 'Chiave o REF di riga non valido'; end if;
  keys:=array_append(keys,l->>'key');q:=(l->>'quantity')::numeric;
  if q is null or q::text in ('NaN','Infinity','-Infinity') or q=0 or trunc(q)<>q or abs(q)>2147483647
  or (p_kind<>'CHIUSURA' and q<0) then raise exception 'Quantità non valida'; end if;
  if p_kind in ('ORDINE','CHIUSURA') and coalesce(l->>'cac','') !~ '^[0-9]+$' then raise exception 'Presidio/CAC obbligatorio'; end if;
  if p_kind='ORDINE' and coalesce(btrim(l->>'po'),'')='' then raise exception 'PO cliente obbligatorio'; end if;
  if p_kind='CHIUSURA' and q>0 and (coalesce(btrim(l->>'po'),'')='' or coalesce(btrim(l->>'invoice'),'')='') then raise exception 'Fattura e PO obbligatori per una vendita'; end if;
  if l->>'price' is not null and ((l->>'price')::numeric)::text in ('NaN','Infinity','-Infinity') then raise exception 'Prezzo non valido'; end if;
  if l->>'total' is not null and ((l->>'total')::numeric)::text in ('NaN','Infinity','-Infinity') then raise exception 'Totale non valido'; end if;
  if l->>'price' is not null and l->>'total' is not null and abs((l->>'price')::numeric*q-(l->>'total')::numeric)>0.02 then raise exception 'Prezzo e totale discordanti'; end if;
 end loop;
end $$;

create or replace function public.jj_business_payload(p_payload jsonb)
returns jsonb language sql immutable security invoker set search_path=public as $$
 select (p_payload-'lines')||jsonb_build_object('lines',coalesce((select jsonb_agg(value-'source_rows' order by value->>'key') from jsonb_array_elements(p_payload->'lines')),'[]'::jsonb));
$$;

create or replace function public.jj_import_records(p_kind text,p_division text,p_file text,p_records jsonb,p_actor text)
returns jsonb language plpgsql security invoker set search_path=public as $$
declare r jsonb;old public.jj_recon_records%rowtype;new_id bigint;n integer:=0;u integer:=0;d integer:=0;p integer:=0;seen text[]:='{}';
begin
 if p_kind is null or p_kind not in ('IMPIANTO','ORDINE','CHIUSURA') or p_division is null or p_division not in ('TRAUMA','PROTESICA')
 or coalesce(btrim(p_actor),'')='' or coalesce(btrim(p_file),'')='' or jsonb_typeof(p_records) is distinct from 'array' or jsonb_array_length(p_records)=0 then raise exception 'Importazione non valida'; end if;
 perform pg_advisory_xact_lock(hashtext('jj-guided-reconciliation'));
 for r in select value from jsonb_array_elements(p_records) loop
  if p_kind='CHIUSURA' and r->>'source_key' is distinct from r->'payload'->>'month' then raise exception 'Periodo e chiave della chiusura discordanti'; end if;
  if p_kind='ORDINE' and coalesce(r->'payload'->>'number','')<>'' and exists(
    select 1 from public.jj_recon_records where kind='ORDINE' and division=p_division
    and payload->>'number'=r->'payload'->>'number' and payload->>'cac'=r->'payload'->>'cac'
    and source_key<>r->>'source_key') then raise exception 'Numero ordine J&J già acquisito con un’altra chiave'; end if;
  if coalesce(r->>'source_key','')='' or (r->>'source_key')=any(seen) then raise exception 'Chiave documento assente o duplicata'; end if;
  seen:=array_append(seen,r->>'source_key');perform public.jj_validate_payload(p_kind,r->'payload');
  select * into old from public.jj_recon_records where kind=p_kind and division=p_division and source_key=r->>'source_key' for update;
  if not found then
   insert into public.jj_recon_records(kind,division,source_key,payload,source_file) values(p_kind,p_division,r->>'source_key',r->'payload',p_file) returning id into new_id;
   insert into public.jj_recon_audit(record_id,action,after_value,actor) values(new_id,'IMPORT',r->'payload',p_actor);n:=n+1;
  elsif public.jj_business_payload(old.payload)=public.jj_business_payload(r->'payload') or public.jj_business_payload(old.pending_payload)=public.jj_business_payload(r->'payload') then d:=d+1;
  elsif old.closed_at is not null or exists(select 1 from public.jj_recon_links where revoked_at is null and old.id in (closure_id,order_id,implant_id)) then
   insert into public.jj_recon_audit(record_id,action,before_value,after_value,actor)
   select c.id,'REOPEN_SOURCE_CHANGED',jsonb_build_object('closed_at',c.closed_at),jsonb_build_object('source_id',old.id),p_actor
   from public.jj_recon_records c where c.closed_at is not null and (c.id=old.id or c.id in
     (select closure_id from public.jj_recon_links where revoked_at is null and old.id in (closure_id,order_id,implant_id)));
   update public.jj_recon_records set closed_at=null where closed_at is not null and (id=old.id or id in
     (select closure_id from public.jj_recon_links where revoked_at is null and old.id in (closure_id,order_id,implant_id)));
   update public.jj_recon_records set pending_payload=r->'payload',source_file=p_file,updated_at=now() where id=old.id;
   insert into public.jj_recon_audit(record_id,action,before_value,after_value,actor) values(old.id,'REVISION_PENDING',old.payload,r->'payload',p_actor);p:=p+1;
  else
   update public.jj_recon_records set payload=r->'payload',source_file=p_file,updated_at=now() where id=old.id;
   insert into public.jj_recon_audit(record_id,action,before_value,after_value,actor) values(old.id,'UPDATE',old.payload,r->'payload',p_actor);u:=u+1;
  end if;
 end loop;
 return jsonb_build_object('nuovi',n,'aggiornati',u,'invariati',d,'revisioni_da_verificare',p);
end $$;

create or replace function public.jj_confirm_links(p_links jsonb,p_actor text)
returns integer language plpgsql security invoker set search_path=public as $$
declare r jsonb;c public.jj_recon_records%rowtype;o public.jj_recon_records%rowtype;i public.jj_recon_records%rowtype;
 a jsonb;b jsonb;d jsonb;q integer;n integer:=0;used integer;existing_q integer;method text;
begin
 if coalesce(btrim(p_actor),'')='' or jsonb_typeof(p_links) is distinct from 'array' or jsonb_array_length(p_links)=0 then raise exception 'Seleziona almeno un abbinamento'; end if;
 perform pg_advisory_xact_lock(hashtext('jj-guided-reconciliation'));
 for r in select value from jsonb_array_elements(p_links) loop
  if coalesce((r->>'quantity')::numeric,0)<=0 or trunc((r->>'quantity')::numeric)<>(r->>'quantity')::numeric then raise exception 'Quantità deve essere intera e positiva'; end if;q:=(r->>'quantity')::integer;
  select * into strict c from public.jj_recon_records where id=(r->>'closure_id')::bigint;
  select * into strict o from public.jj_recon_records where id=(r->>'order_id')::bigint;
  select * into strict i from public.jj_recon_records where id=(r->>'implant_id')::bigint;
  if c.kind<>'CHIUSURA' or o.kind<>'ORDINE' or i.kind<>'IMPIANTO' or c.division<>o.division or c.division<>i.division then raise exception 'Tipi o divisioni discordanti'; end if;
  if c.pending_payload is not null or o.pending_payload is not null or i.pending_payload is not null or c.closed_at is not null then raise exception 'Revisione da verificare o mese già chiuso'; end if;
  select value into a from jsonb_array_elements(c.payload->'lines') where value->>'key'=r->>'closure_line';
  select value into b from jsonb_array_elements(o.payload->'lines') where value->>'key'=r->>'order_line';
  select value into d from jsonb_array_elements(i.payload->'lines') where value->>'key'=r->>'implant_line';
  if a is null or b is null or d is null or a->>'ref'<>b->>'ref' or a->>'ref'<>d->>'ref'
  or coalesce(a->>'cac','')='' or a->>'cac' is distinct from b->>'cac' or a->>'cac' is distinct from d->>'cac'
  or coalesce(a->>'po','')='' or upper(btrim(a->>'po')) is distinct from upper(btrim(b->>'po')) then raise exception 'REF, presidio o PO discordanti'; end if;
  if coalesce(a->>'invoice','')<>'' and coalesce(b->>'invoice','')<>'' and split_part(a->>'invoice','-',1)<>split_part(b->>'invoice','-',1) then raise exception 'Fattura discordante'; end if;
  if coalesce(b->>'lot','')<>'' and coalesce(d->>'lot','')<>'' and b->>'lot'<>d->>'lot' then raise exception 'Lotto discordante'; end if;
  if coalesce(a->>'date','')<>'' and coalesce(i.payload->>'event_date','')<>'' and (i.payload->>'event_date')::date>(a->>'date')::date then raise exception 'Intervento successivo alla fattura'; end if;
  select quantity into existing_q from public.jj_recon_links where revoked_at is null and closure_id=c.id and closure_line=r->>'closure_line' and order_id=o.id and order_line=r->>'order_line' and implant_id=i.id and implant_line=r->>'implant_line';
  if found then if existing_q<>q then raise exception 'Abbinamento esistente con quantità diversa: annullarlo prima'; end if;continue;end if;
  select coalesce(sum(quantity),0) into used from public.jj_recon_links where revoked_at is null and closure_id=c.id and closure_line=r->>'closure_line';
  if used+q>(a->>'quantity')::integer then raise exception 'Quantità fatturata già utilizzata'; end if;
  select coalesce(sum(quantity),0) into used from public.jj_recon_links where revoked_at is null and order_id=o.id and order_line=r->>'order_line';
  if used+q>(b->>'quantity')::integer then raise exception 'Quantità ordine già utilizzata'; end if;
  select coalesce(sum(quantity),0) into used from public.jj_recon_links where revoked_at is null and implant_id=i.id and implant_line=r->>'implant_line';
  if used+q>(d->>'quantity')::integer then raise exception 'Quantità impianto già utilizzata'; end if;
  method:=case when coalesce(b->>'lot','')='' then 'MANUALE_REF_QUANTITA_SENZA_LOTTO_ORDINE' else 'MANUALE_REF_LOTTO_QUANTITA' end;
  insert into public.jj_recon_links(closure_id,closure_line,order_id,order_line,implant_id,implant_line,quantity,method,actor)
  values(c.id,r->>'closure_line',o.id,r->>'order_line',i.id,r->>'implant_line',q,method,p_actor);
  insert into public.jj_recon_audit(record_id,action,after_value,actor) values(c.id,'CONFIRM_LINK',r||jsonb_build_object('method',method),p_actor);n:=n+1;
 end loop;return n;
end $$;

create or replace function public.jj_review_record(p_id bigint,p_action text,p_payload jsonb,p_note text,p_actor text)
returns void language plpgsql security invoker set search_path=public as $$
declare old public.jj_recon_records%rowtype;l jsonb;used integer;new_payload jsonb;
begin
 if coalesce(btrim(p_actor),'')='' or coalesce(btrim(p_note),'')='' then raise exception 'Utente e motivazione obbligatori'; end if;
 perform pg_advisory_xact_lock(hashtext('jj-guided-reconciliation'));
 select * into strict old from public.jj_recon_records where id=p_id for update;
 if p_action='CLOSE' then
  if old.kind<>'CHIUSURA' or old.pending_payload is not null then raise exception 'Chiusura non confermabile'; end if;
  for l in select value from jsonb_array_elements(old.payload->'lines') loop
   if (l->>'quantity')::integer>0 then
    select coalesce(sum(quantity),0) into used from public.jj_recon_links where revoked_at is null and closure_id=p_id and closure_line=l->>'key';
    if used<>(l->>'quantity')::integer then raise exception 'Restano righe fatturate da riconciliare'; end if;
   end if;
  end loop;
  if exists(select 1 from public.jj_recon_links x join public.jj_recon_records r on r.id in (x.order_id,x.implant_id) where x.closure_id=p_id and x.revoked_at is null and r.pending_payload is not null) then raise exception 'Documenti collegati con revisioni pendenti'; end if;
  update public.jj_recon_records set closed_at=now() where id=p_id;
 elsif p_action='REOPEN' then
  if old.kind<>'CHIUSURA' then raise exception 'Solo una chiusura può essere riaperta'; end if;
  update public.jj_recon_records set closed_at=null where id=p_id;
 elsif p_action in ('ACCEPT_REVISION','EDIT') then
  new_payload:=case when p_action='ACCEPT_REVISION' then old.pending_payload else p_payload end;
  if new_payload is null then raise exception 'Nessuna revisione disponibile'; end if;
  perform public.jj_validate_payload(old.kind,new_payload);
  update public.jj_recon_records set closed_at=null where id in
   (select closure_id from public.jj_recon_links where revoked_at is null and p_id in (closure_id,order_id,implant_id));
  -- An explicit reviewed edit invalidates linked evidence, but never deletes history.
  update public.jj_recon_links set revoked_at=now() where revoked_at is null and p_id in (closure_id,order_id,implant_id);
  update public.jj_recon_records set payload=new_payload,pending_payload=null,closed_at=null,updated_at=now() where id=p_id;
 else raise exception 'Azione non valida';end if;
 insert into public.jj_recon_audit(record_id,action,before_value,after_value,actor) values(p_id,p_action,to_jsonb(old),jsonb_build_object('payload',new_payload,'note',p_note),p_actor);
end $$;
create or replace function public.jj_map_customer(p_customer text,p_cac text,p_division text,p_actor text)
returns integer language plpgsql security invoker set search_path=public as $$
declare r public.jj_recon_records%rowtype;p jsonb;n integer:=0;
begin
 if regexp_replace(upper(btrim(p_customer)),'[^A-Z0-9]+',' ','g')='ASL SALERNO' then raise exception 'ASL Salerno comprende più presidi: assegnare il singolo documento'; end if;
 if coalesce(p_cac,'') !~ '^[0-9]+$' or coalesce(btrim(p_actor),'')='' then raise exception 'Presidio e utente obbligatori'; end if;
 perform pg_advisory_xact_lock(hashtext('jj-guided-reconciliation'));
 for r in select * from public.jj_recon_records where kind='IMPIANTO' and division=p_division and btrim(payload->>'customer')=btrim(p_customer) loop
  if r.payload->>'cac'=p_cac then continue;end if;
  if r.pending_payload is not null then raise exception 'Verificare prima la revisione del documento %',r.source_key; end if;
  select jsonb_set(jsonb_set(r.payload,'{cac}',to_jsonb(p_cac)),'{lines}',jsonb_agg(value||jsonb_build_object('cac',p_cac))) into p from jsonb_array_elements(r.payload->'lines');
  perform public.jj_review_record(r.id,'EDIT',p,'Assegnazione presidio confermata per cliente '||p_customer,p_actor);n:=n+1;
 end loop;return n;
end $$;

create or replace function public.jj_revoke_link(p_id bigint,p_note text,p_actor text)
returns void language plpgsql security invoker set search_path=public as $$
declare old public.jj_recon_links%rowtype;
begin
 if coalesce(btrim(p_actor),'')='' or coalesce(btrim(p_note),'')='' then raise exception 'Motivazione obbligatoria'; end if;
 perform pg_advisory_xact_lock(hashtext('jj-guided-reconciliation'));
 select * into strict old from public.jj_recon_links where id=p_id;
 if exists(select 1 from public.jj_recon_records where id=old.closure_id and closed_at is not null) then raise exception 'Riaprire prima il mese'; end if;
 update public.jj_recon_links set revoked_at=now() where id=p_id and revoked_at is null;
 insert into public.jj_recon_audit(record_id,action,before_value,after_value,actor) values(old.closure_id,'REVOKE_LINK',to_jsonb(old),jsonb_build_object('note',p_note),p_actor);
end $$;
revoke all on function public.jj_validate_payload(text,jsonb),public.jj_import_records(text,text,text,jsonb,text),public.jj_confirm_links(jsonb,text),public.jj_review_record(bigint,text,jsonb,text,text),public.jj_revoke_link(bigint,text,text) from public,anon,authenticated;
grant execute on function public.jj_validate_payload(text,jsonb),public.jj_import_records(text,text,text,jsonb,text),public.jj_confirm_links(jsonb,text),public.jj_review_record(bigint,text,jsonb,text,text),public.jj_revoke_link(bigint,text,text) to service_role;
revoke all on function public.jj_map_customer(text,text,text,text) from public,anon,authenticated;
grant execute on function public.jj_map_customer(text,text,text,text) to service_role;
revoke all on function public.jj_business_payload(jsonb) from public,anon,authenticated;
grant execute on function public.jj_business_payload(jsonb) to service_role;
