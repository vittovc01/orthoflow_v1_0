-- STAGING ONLY. Never run on the operational project.
do $$ begin
 if current_setting('orthoflow.environment',true) is distinct from 'staging' then
   raise exception 'STAGING_REQUIRED';
 end if;
end $$;
create table if not exists public.orthoflow_environment (
 singleton boolean primary key default true check(singleton), environment text not null check(environment='staging')
);
insert into public.orthoflow_environment values(true,'staging') on conflict do nothing;
alter table public.orthoflow_environment enable row level security;
create table if not exists public.articoli_gtin (
 gtin text primary key check(gtin ~ '^[0-9]{14}$'), ref text not null check(length(trim(ref))>0),
 descrizione text, categoria text, fonte_file text not null, fonte_versione text not null,
 fonte_sha256 text not null, importato_il timestamptz not null default now()
);
-- Existing three-column staging installations retain their records.
alter table public.articoli_gtin add column if not exists categoria text;
alter table public.articoli_gtin add column if not exists fonte_file text;
alter table public.articoli_gtin add column if not exists fonte_versione text;
alter table public.articoli_gtin add column if not exists fonte_sha256 text;
alter table public.articoli_gtin add column if not exists importato_il timestamptz default now();
create index if not exists articoli_gtin_ref_idx on public.articoli_gtin(ref);
alter table public.articoli_gtin enable row level security;
revoke all on public.articoli_gtin,public.orthoflow_environment from public,anon,authenticated;
grant select,insert,update on public.articoli_gtin to service_role;
grant select on public.orthoflow_environment to service_role;

create or replace function public.import_articoli_gtin_staging(
 p_rows jsonb,p_source_file text,p_source_version text,p_source_sha256 text,p_discarded integer default 0
) returns jsonb language plpgsql security invoker set search_path=public as $$
declare fresh integer; changed integer; unchanged integer; total integer;
begin
 if not exists(select 1 from public.orthoflow_environment where singleton and environment='staging') then
   raise exception 'STAGING_REQUIRED';
 end if;
 if jsonb_typeof(p_rows) is distinct from 'array' or jsonb_array_length(p_rows)=0
    or coalesce(p_source_file,'')='' or coalesce(p_source_version,'')=''
    or coalesce(p_source_sha256,'') !~ '^[0-9a-f]{64}$' or p_discarded<0 then
   raise exception 'INVALID_IMPORT';
 end if;
 if exists(select 1 from jsonb_to_recordset(p_rows) as r(gtin text,ref text)
    where coalesce(gtin,'') !~ '^[0-9]{14}$' or coalesce(trim(ref),'')='') then
   raise exception 'INVALID_GTIN_OR_REF';
 end if;
 if exists(select 1 from jsonb_to_recordset(p_rows) as r(gtin text,ref text)
    where (select sum(substr(gtin,i,1)::int * case when i%2=1 then 3 else 1 end)
           from generate_series(1,13) as s(i))%10 <> (10-right(gtin,1)::int)%10) then
   raise exception 'INVALID_GTIN_CHECKSUM';
 end if;
 if exists(select 1 from jsonb_to_recordset(p_rows) as r(gtin text,ref text)
    group by gtin having count(distinct ref)>1) then raise exception 'GTIN_REF_CONFLICT_IN_FILE'; end if;
 -- Serialize catalogue writers; no conflicting record can slip past the preflight.
 lock table public.articoli_gtin in share row exclusive mode;
 if exists(select 1 from jsonb_to_recordset(p_rows) as r(gtin text,ref text)
    join public.articoli_gtin t using(gtin) where r.ref<>t.ref) then
   raise exception 'GTIN_REF_CONFLICT_IN_DATABASE';
 end if;
 with incoming as (select distinct on(gtin) * from jsonb_to_recordset(p_rows)
     as r(gtin text,ref text,descrizione text,categoria text) order by gtin),
 classified as (
 select r.*,t.gtin is null as is_new,
    (t.descrizione,t.categoria,t.fonte_file,t.fonte_versione,t.fonte_sha256)
       is distinct from (coalesce(r.descrizione,t.descrizione),coalesce(r.categoria,t.categoria),
                         p_source_file,p_source_version,p_source_sha256) as is_changed
 from incoming r left join public.articoli_gtin t using(gtin))
 select count(*) filter(where is_new),count(*) filter(where not is_new and is_changed),
        count(*) filter(where not is_new and not is_changed),count(*)
 into fresh,changed,unchanged,total from classified;
 insert into public.articoli_gtin as t(gtin,ref,descrizione,categoria,fonte_file,fonte_versione,fonte_sha256)
 select distinct on(gtin) gtin,ref,descrizione,categoria,p_source_file,p_source_version,p_source_sha256
 from jsonb_to_recordset(p_rows) as r(gtin text,ref text,descrizione text,categoria text) order by gtin
 on conflict(gtin) do update set descrizione=coalesce(excluded.descrizione,t.descrizione),
 categoria=coalesce(excluded.categoria,t.categoria),fonte_file=excluded.fonte_file,
 fonte_versione=excluded.fonte_versione,fonte_sha256=excluded.fonte_sha256,importato_il=now()
 where (t.descrizione,t.categoria,t.fonte_file,t.fonte_versione,t.fonte_sha256)
    is distinct from (coalesce(excluded.descrizione,t.descrizione),coalesce(excluded.categoria,t.categoria),
                      excluded.fonte_file,excluded.fonte_versione,excluded.fonte_sha256);
 return jsonb_build_object('nuove',fresh,'aggiornate',changed,'invariate',unchanged,
                          'scartate',p_discarded,'valide_distinte',total);
end $$;
revoke all on function public.import_articoli_gtin_staging(jsonb,text,text,text,integer) from public,anon,authenticated;
grant execute on function public.import_articoli_gtin_staging(jsonb,text,text,text,integer) to service_role;
