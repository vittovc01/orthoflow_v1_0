# Staging-only catalogue import

`catalog_import.py` accepts UTF-8 CSV with `gtin,ref` and optional `descrizione,categoria`. GTINs remain text with leading zeros, validate their checksum, and form the primary key. All rows/categories are processed. Missing categories remain NULL. Conflicting REFs for a GTIN abort the import. Invalid records and identical duplicates are reported as discarded.

The online client requires explicit staging identification and rejects the known operational project. Apply `sql/staging_gtin_catalog.sql` only on a verified, separate staging project after setting `orthoflow.environment=staging`. The RPC imports atomically and reports new, updated, unchanged and discarded rows; repeated identical imports do not change timestamps. Existing mappings cannot silently change REF.

Local reproducible integration check, without network database access:

```bash
npm ci --prefix tools/gtin-staging --ignore-scripts
python catalog_import.py tests/fixtures/gtin_catalog_minimal.csv --source-version ci --payload /tmp/catalog-payload.json
node tools/gtin-staging/run.mjs /tmp/catalog-payload.json /tmp/new-gtin-db /tmp/gtin-report.json
```

The pinned WASM runtime runs PostgreSQL 17. Tests check first import, idempotent repeat, REF conflict, metadata update followed by rollback, and anonymous access denial. Use a fresh directory to measure first-import counts. CI uses synthetic identifiers only. Never commit a proprietary catalogue, real review records, credentials, or local database files.

Quantity rules: distinct physical stickers with the same REF/lot aggregate to quantity 2. Identical rendered documents are analyzed once, even when file encoding differs. Different photos with equal REF/lot require an explicit operator review: exclude repeated observations of the same sticker, retain distinct physical stickers. No silent merging based on product identity. Partial PDF page overlap is not automatically deduplicated.

Hosted staging remains a separate deployment prerequisite; a local PostgreSQL test does not certify Supabase RLS/Storage or the published app. Keep the OCR archive disabled until hosted staging, operator review, permissions, retention, retries and restore are validated. No production catalogue import is authorized by this change.
