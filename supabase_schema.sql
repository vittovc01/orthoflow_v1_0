
-- ORTHOFLOW CONTROL TOWER - SUPABASE SCHEMA V0.5

create table if not exists clienti (
  id bigserial primary key,
  codice_cliente text unique,
  descrizione text,
  citta text,
  provincia text,
  piva text,
  created_at timestamptz default now()
);

create table if not exists agenti (
  id bigserial primary key,
  nome text unique not null,
  created_at timestamptz default now()
);

create table if not exists magazzino (
  id bigserial primary key,
  codice text not null,
  descrizione text,
  lotto text not null,
  scadenza text,
  quantita numeric default 0,
  ubicazione text,
  origine text default 'CONTO DEPOSITO',
  created_at timestamptz default now(),
  unique(codice, lotto, origine)
);

create table if not exists offerte_header (
  id bigserial primary key,
  nome_offerta text,
  linea text,
  data_inizio date,
  data_fine date,
  note text,
  created_at timestamptz default now()
);

create table if not exists offerte_clienti (
  id bigserial primary key,
  offerta_id bigint references offerte_header(id) on delete cascade,
  codice_cliente text,
  created_at timestamptz default now()
);

create table if not exists offerte_prezzi (
  id bigserial primary key,
  offerta_id bigint references offerte_header(id) on delete cascade,
  codice text,
  descrizione text,
  prezzo numeric,
  iva text,
  cnd text,
  rdm text,
  created_at timestamptz default now()
);

create table if not exists interventi (
  id bigserial primary key,
  data_intervento date,
  codice_cliente text,
  cliente text,
  cartella_clinica text,
  agente text,
  chirurgo text,
  linea text,
  allegato text,
  note text,
  created_at timestamptz default now()
);

create table if not exists righe_intervento (
  id bigserial primary key,
  intervento_id bigint references interventi(id) on delete cascade,
  codice text,
  descrizione text,
  lotto text,
  scadenza text,
  quantita numeric,
  produttore text,
  validazione text,
  origine text,
  prezzo numeric,
  totale numeric,
  reintegro boolean default true,
  created_at timestamptz default now()
);

create table if not exists ddt (
  id bigserial primary key,
  numero_ddt text,
  data_ddt date,
  tipo_ddt text,
  cliente text,
  allegato text,
  note text,
  created_at timestamptz default now()
);

create table if not exists ddt_righe (
  id bigserial primary key,
  ddt_id bigint references ddt(id) on delete cascade,
  codice text,
  descrizione text,
  lotto text,
  scadenza text,
  quantita numeric,
  origine text,
  created_at timestamptz default now()
);

create table if not exists order_history (
  id bigserial primary key,
  numero_ordine text,
  riferimento_po text,
  data_ordine date,
  cliente text,
  stato text,
  totale numeric,
  created_at timestamptz default now()
);

create table if not exists order_details (
  id bigserial primary key,
  numero_ordine text,
  codice text,
  descrizione text,
  quantita numeric,
  prezzo numeric,
  totale numeric,
  created_at timestamptz default now()
);

create table if not exists chiusure (
  id bigserial primary key,
  mese text,
  numero_ordine text,
  codice text,
  descrizione text,
  quantita numeric,
  valore numeric,
  created_at timestamptz default now()
);

create table if not exists anomalie (
  id bigserial primary key,
  tipo text,
  gravita text,
  descrizione text,
  stato text default 'Aperta',
  created_at timestamptz default now()
);

-- Storage bucket per allegati
insert into storage.buckets (id, name, public)
values ('orthoflow-documents', 'orthoflow-documents', false)
on conflict (id) do nothing;

-- Indici utili
create index if not exists idx_magazzino_codice_lotto on magazzino(codice, lotto);
create index if not exists idx_offerte_prezzi_codice on offerte_prezzi(codice);
create index if not exists idx_interventi_cliente_data on interventi(codice_cliente, data_intervento);
create index if not exists idx_righe_intervento_codice_lotto on righe_intervento(codice, lotto);


-- V1.0 users / roles
create table if not exists utenti (
  id bigserial primary key,
  username text unique not null,
  password_hash text,
  nome text,
  ruolo text default 'Agente',
  attivo boolean default true,
  created_at timestamptz default now()
);

create table if not exists audit_log (
  id bigserial primary key,
  utente text,
  azione text,
  tabella text,
  riferimento text,
  dettagli jsonb,
  created_at timestamptz default now()
);

create table if not exists loan_monitor (
  id bigserial primary key,
  codice text,
  lotto text,
  descrizione text,
  quantita numeric,
  ddt_id bigint,
  stato text default 'APERTO',
  data_arrivo date,
  data_utilizzo date,
  data_restituzione date,
  note text,
  created_at timestamptz default now()
);

create index if not exists idx_loan_codice_lotto on loan_monitor(codice, lotto);
create index if not exists idx_anomalie_stato on anomalie(stato);
