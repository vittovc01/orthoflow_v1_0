-- TEST ONLY: contract subset of live schema, without production rows.
-- Match Supabase service_role semantics in the disposable local database.
ALTER ROLE service_role BYPASSRLS;
CREATE TABLE utenti_app(id bigserial PRIMARY KEY,username text NOT NULL,attivo boolean NOT NULL DEFAULT true,
 stato_accesso text NOT NULL DEFAULT 'APPROVATO',ruolo text NOT NULL,permessi text[] NOT NULL DEFAULT '{}',agente_nome text);
CREATE TABLE corrieri(id bigserial PRIMARY KEY,user_id bigint,attivo boolean NOT NULL DEFAULT true);
CREATE TABLE strutture_logistiche(id bigserial PRIMARY KEY,nome text);
CREATE TABLE missioni_corrieri(id bigserial PRIMARY KEY,codice text,data_missione date DEFAULT current_date,
 corriere_id bigint,struttura_id bigint,tipo text,kit_codice text,colli integer,stato text DEFAULT 'PROGRAMMATA',
 esito_firma_ritiro text,nota_firma_ritiro text,updated_at timestamptz DEFAULT now());
CREATE TABLE timbrature_corrieri(id bigserial PRIMARY KEY,missione_id bigint,corriere_id bigint,struttura_id bigint,
 tipo text,latitudine numeric,longitudine numeric,precisione_m numeric,created_at timestamptz DEFAULT now());
CREATE TABLE foto_missioni(id bigserial PRIMARY KEY,missione_id bigint,tipo text,storage_path text);
CREATE TABLE documenti_missioni(id bigserial PRIMARY KEY,missione_id bigint,tipo_documento text,storage_path text,
 firma_storage_path text,nome_firmatario text,ruolo_firmatario text,firmato_at timestamptz);
CREATE TABLE movimenti_kit_corrieri(id bigserial PRIMARY KEY,kit_id bigint,missione_id bigint,corriere_id bigint,
 struttura_id bigint,movimento text,stato_precedente text,stato_nuovo text,utente text);
CREATE TABLE clienti(id bigserial PRIMARY KEY,codice_cliente text,agente text);
ALTER TABLE kit_logistici ADD COLUMN codice text,ADD COLUMN stato text DEFAULT 'IN_MAGAZZINO',
 ADD COLUMN struttura_id bigint,ADD COLUMN missione_id bigint,ADD COLUMN corriere_id bigint,
 ADD COLUMN updated_at timestamptz DEFAULT now(),ADD COLUMN codice_magazzino text;
ALTER TABLE reintegri_kit ADD COLUMN lotto_consumato text,ADD COLUMN stato text,ADD COLUMN utente text;
GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;
GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO service_role;
