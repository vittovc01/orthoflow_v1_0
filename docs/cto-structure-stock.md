# Conto deposito struttura: CTO / Ospedale dei Colli

Enabled customer codes are Malzoni `9010013` and the registered
**Ospedale C.T.O. `9010054`**. Matching is by customer code, never a fuzzy name.

In Scarico Sala AI the editable ownership checkbox appears for both customers.
Checked rows retain product, lot, expiry, quantity, price and revenue, with origin
`CONTO DEPOSITO STRUTTURA`. They skip our stock checks, debit, stock movements,
stock anomalies and kit replenishment. Unchecked rows follow normal stock rules.
No existing intervention, ownership choice or stock balance is backfilled.

`sql/cto_structure_stock.sql` updates the existing flexible/verified RPC guards,
the structure-anomaly trigger and repricing trigger. It patches their live
function definitions rather than replacing later unrelated fixes. The operation
is transactional/idempotent and preserves signatures, owners and grants.
A missing/unrecognized function aborts the migration.

A customer change is blocked while structure-owned rows remain, including a
change from CTO to Malzoni: material owned by one hospital cannot silently become
material of another. A line-only change at the same enabled customer can still
reprice normally.

Validation uses synthetic records in an isolated database only:

- mixed flexible CTO discharge: our quantity 2 is debited, hospital quantities
  3+1 stay in revenue, only one stock movement, no hospital stock anomaly;
- verified v2 CTO discharge: our quantity 1 is debited, hospital quantity 1 stays
  in revenue, replay has no second debit, cross-hospital reassignment is blocked,
  line changes remain allowed and structure anomalies close correctly;
- unsupported customers remain rejected and Malzoni behavior is retained;
- SQL migration applied twice in CI; existing validation, idempotency and repricing
  suites remain required;
- actual Streamlit tests toggle ownership repeatedly for both customer codes
  and assert the final RPC flags, without a real backend or stock write.
