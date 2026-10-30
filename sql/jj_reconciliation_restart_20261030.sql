-- One-off authorized restart of both administrative ledgers; never run at app startup.
-- The private snapshot retains original rows/IDs. Replay never clears later imports.
create schema if not exists orthoflow_maintenance;
revoke all on schema orthoflow_maintenance from public,anon,authenticated,service_role;
create table if not exists orthoflow_maintenance.reconciliation_resets(
 reset_key text primary key, created_at timestamptz not null default now(),
 actor text not null, reason text not null, snapshot jsonb not null,
 operational_verification jsonb not null);
alter table orthoflow_maintenance.reconciliation_resets enable row level security;
revoke all on orthoflow_maintenance.reconciliation_resets from public,anon,authenticated,service_role;

do $$
declare
 reset_id constant text := 'vittorio_fresh_start_2026_10_30';
 -- Children before parents. No CASCADE and no operational tables.
 tables_to_clear constant text[] := array[
  'jj_recon_links','jj_recon_audit','jj_recon_records',
  'esiti_chiusura_johnson','righe_chiusura_johnson','chiusure_mensili_johnson',
  'riconciliazioni_reintegro_jj','riconciliazioni_johnson',
  'righe_ddt_johnson','ddt_johnson','fatture_johnson',
  'righe_ordini_johnson','ordini_johnson'];
 operational constant text[] := array['interventi','righe_intervento','movimenti_magazzino','giacenze'];
 saved jsonb := '{}'::jsonb; before_state jsonb := '{}'::jsonb;
 table_name text; rows_json jsonb; fingerprint text; remaining bigint;
begin
 perform pg_advisory_xact_lock(hashtext('jj-guided-reconciliation'));
 if exists(select 1 from orthoflow_maintenance.reconciliation_resets where reset_key=reset_id) then return; end if;
 foreach table_name in array tables_to_clear loop
  execute format('lock table public.%I in access exclusive mode',table_name);
 end loop;
 foreach table_name in array operational loop
  execute format('lock table public.%I in share mode',table_name);
  execute format('select md5(coalesce(jsonb_agg(to_jsonb(t) order by id)::text,''[]'')) from public.%I t',table_name) into fingerprint;
  before_state:=before_state||jsonb_build_object(table_name,fingerprint);
 end loop;
 foreach table_name in array tables_to_clear loop
  execute format('select coalesce(jsonb_agg(to_jsonb(t) order by id),''[]''::jsonb) from public.%I t',table_name) into rows_json;
  saved:=saved||jsonb_build_object(table_name,rows_json);
 end loop;
 insert into orthoflow_maintenance.reconciliation_resets(reset_key,actor,reason,snapshot,operational_verification)
 values(reset_id,'Vittorio Cremonese / richiesta 30-10-2026',
  'Unificare in Chiusura guidata e ripartire con caricamenti manuali dell’utente',saved,before_state);
 foreach table_name in array tables_to_clear loop
  execute format('delete from public.%I',table_name);
  execute format('select count(*) from public.%I',table_name) into remaining;
  if remaining<>0 then raise exception 'Registro % non svuotato',table_name; end if;
 end loop;
 foreach table_name in array operational loop
  execute format('select md5(coalesce(jsonb_agg(to_jsonb(t) order by id)::text,''[]'')) from public.%I t',table_name) into fingerprint;
  if fingerprint is distinct from before_state->>table_name then
   raise exception 'Dati operativi modificati durante il riavvio: %',table_name;
  end if;
 end loop;
end $$;
