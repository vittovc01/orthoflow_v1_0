#!/usr/bin/env bash
set -euo pipefail
# Fixed local service only. A production DATABASE_URL is never read.
export PGHOST=127.0.0.1 PGPORT=5432 PGUSER=postgres PGDATABASE=orthoflow_ci PGPASSWORD=ci_only
psql -X -v ON_ERROR_STOP=1 -f tests/fixtures/database.sql
psql -X -v ON_ERROR_STOP=1 -f tests/fixtures/mobile_database.sql
for migration in sql/malzoni_structure_stock.sql sql/fix_ai_stock_double_debit.sql sql/remember_manual_structure_prices.sql sql/delete_intervention_complete.sql sql/close_structure_stock_anomalies.sql sql/mobile_operations.sql sql/cloud_capacity.sql sql/server_only_security.sql; do
  psql -X -v ON_ERROR_STOP=1 -f "$migration"
done
psql -X -v ON_ERROR_STOP=1 -c "CREATE TRIGGER trg_movimenti_giacenza AFTER INSERT ON movimenti_magazzino FOR EACH ROW EXECUTE FUNCTION aggiorna_giacenza_da_movimento();"
for test in tests/*.sql; do
  printf 'Running %s\n' "$test"
  psql -X -v ON_ERROR_STOP=1 -f "$test"
done

