#!/usr/bin/env bash
set -euo pipefail
# Never consume a production connection string.
export PGHOST=127.0.0.1 PGPORT=5432 PGUSER=postgres PGDATABASE=orthoflow_ci PGPASSWORD=ci_only
trial_dir=$(mktemp -d)
trap 'rm -rf "$trial_dir"' EXIT
psql -X -v ON_ERROR_STOP=1 <<'SQL'
INSERT INTO giacenze(codice_magazzino,codice,lotto,scadenza,quantita,origine)
VALUES('TEST-CONCURRENT','TEST-A','TEST-LOT','2035-01-01',10,'CONTO DEPOSITO');
CREATE FUNCTION test_slow_discharge() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN IF NEW.magazzino_scarico='TEST-CONCURRENT' THEN PERFORM pg_sleep(1); END IF; RETURN NEW; END $$;
CREATE TRIGGER test_slow_discharge BEFORE INSERT ON interventi FOR EACH ROW EXECUTE FUNCTION test_slow_discharge();
SQL
cat > "$trial_dir/request.sql" <<'SQL'
SELECT crea_intervento_scarico_ai_verificato_v2(
'{"request_id":"00000000-0000-4000-8000-000000000030","data_intervento":"2026-10-16","codice_cliente":"TEST-CONCURRENT","cartella_clinica":"TEST-CONCURRENT","magazzino_scarico":"TEST-CONCURRENT","review_contract_version":2,"count_verified":true,"physical_label_count":1,"included_label_ids":["one"],"label_manifest":[{"label_id":"one","codice":"TEST-A","lotto":"TEST-LOT","scadenza":"2035-01-01","quantita":2}]}',
'[{"codice":"TEST-A","lotto":"TEST-LOT","scadenza":"2035-01-01","quantita":2,"label_ids":["one"],"verificata":true}]', 'test-agent');
SQL
psql -X -v ON_ERROR_STOP=1 -f "$trial_dir/request.sql" > "$trial_dir/one" & first_pid=$!
psql -X -v ON_ERROR_STOP=1 -f "$trial_dir/request.sql" > "$trial_dir/two" & second_pid=$!
wait "$first_pid"
wait "$second_pid"
psql -X -v ON_ERROR_STOP=1 <<'SQL'
DO $$ BEGIN
 IF (SELECT count(*) FROM interventi WHERE magazzino_scarico='TEST-CONCURRENT')<>1
    OR (SELECT quantita FROM giacenze WHERE codice_magazzino='TEST-CONCURRENT')<>8
    OR (SELECT count(*) FROM movimenti_magazzino WHERE codice_magazzino='TEST-CONCURRENT')<>1
    OR (SELECT count(*) FROM audit_log WHERE riferimento IN (SELECT id::text FROM interventi WHERE magazzino_scarico='TEST-CONCURRENT'))<>1 THEN
   RAISE EXCEPTION 'parallel requests created duplicate effects';
 END IF;
END $$;
DROP TRIGGER test_slow_discharge ON interventi;
DROP FUNCTION test_slow_discharge();
SQL
printf 'PASS: two concurrent connections, one intervention, one stock discharge\n'
