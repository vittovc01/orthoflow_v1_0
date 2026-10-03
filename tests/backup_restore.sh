#!/usr/bin/env bash
set -euo pipefail
# Disposable CI service, no production URL accepted.
export PGHOST=127.0.0.1 PGPORT=5432 PGUSER=postgres PGPASSWORD=ci_only
backup_test_dir=$(mktemp -d)
trap 'rm -rf "$backup_test_dir"' EXIT
psql -X -d orthoflow_ci -v ON_ERROR_STOP=1 -c "CREATE TABLE backup_probe(id int PRIMARY KEY, value text); INSERT INTO backup_probe VALUES (1,'LOT-TEST-001');"
pg_dump -d orthoflow_ci --schema=public --format=custom --no-owner --no-acl -f "$backup_test_dir/database.dump"
createdb orthoflow_restore
psql -X -d orthoflow_restore -v ON_ERROR_STOP=1 -c 'DROP SCHEMA public; CREATE SCHEMA storage; CREATE TABLE storage.objects(bucket_id text, name text, metadata jsonb);'
pg_restore -d orthoflow_restore --no-owner --no-acl --exit-on-error "$backup_test_dir/database.dump"
psql -X -d orthoflow_restore -v ON_ERROR_STOP=1 -c "DO \$\$ BEGIN IF (SELECT value FROM backup_probe WHERE id=1) <> 'LOT-TEST-001' THEN RAISE EXCEPTION 'Restore lost values'; END IF; END \$\$;"
