# Physical-label OCR validation — 13 October 2026

Status: review candidate. NOT approved for production activation. No stock discharge,
production schema change, or historical stock repair was performed.

## Changes

- Render PDF at 288 DPI; apply EXIF before photograph decoding.
- Separate geometry detection from isolated per-label reading. The locator proposes
  original-page coordinates and each label's own rotation, including vertical labels.
- Geometric overlap suppression precedes reading. Equal REF/lot observations at
  different positions remain distinct physical pieces.
- Local ZXing DataMatrix decoding with conservative image variants. GS1 AIs
  01/20/17/10 cover the attached Synthes labels. GTIN is never converted to REF.
- Retain failed reads with null identifiers and warnings; compare OCR against GS1.
- Require an explicit physical count and individual operator verification, including
  excluded labels. Immutable label IDs link the editor and original crops.
- Compare REF (normalized for lookup only), exact lot, expiry, and aggregate quantity
  against paginated inventory reads. Missing expiry blocks confirmation.
- Dedicated service-role-only, SECURITY INVOKER RPC repeats verification and stock
  checks under row locks; any shortage rolls back the entire intervention.
- Physical label coordinates, corrected identities and exclusions persist in the existing audit log.
- Existing manual-entry RPC and mobile discharge RPC remain unchanged.

## Existing PRs

PR #22's two commits are included as ancestors, preserving the intervention audit
schema fix. The new AI inventory preflight fetches complete rows rather than relying
on #22's exact-code filter, which can miss a differently punctuated stored REF.
PR #21 was inspected; its overlapping alternate-orientation column strategy was
replaced. It should not be merged after this implementation without reconciliation.
The permission wrapper was inspected and retained: checks run on form submission,
not on disabled-checkbox reruns.

## Santa Lucia reference evidence

The original PDF is upside down. Sixteen separate physical labels were manually
located and visually compared at high resolution. The repository contains only
product-label crops, not the clinical header. The source SHA-256 is recorded in the
manifest. Reference crops and expected identifiers are NOT locator output.

| Label | REF | Lot | Expiry | DataMatrix |
|---|---|---|---|---|
| 1 | 07.720.051S | 502L306 | 2029-12-01 | decoded |
| 2 | 07.720.047S | 460L593 | 2030-09-01 | not decoded; visually verified |
| 3 | 07.720.045S | 502L109 | 2030-07-01 | decoded |
| 4 | 441.903S | 78864P9 | 2035-09-01 | decoded |
| 5 | 292.720S | 477L650 | 2036-03-01 | decoded |
| 6 | 292.720S | 477L650 | 2036-03-01 | decoded |
| 7 | 413.040S | 301931P | 2036-06-01 | decoded |
| 8 | 413.040S | 62405P5 | 2035-04-01 | decoded |
| 9 | 413.048S | 9133P02 | 2034-01-01 | decoded |
| 10 | 04.200.026S | 354L297 | 2034-11-01 | decoded |
| 11 | 413.040S | 66475P9 | 2035-05-01 | decoded |
| 12 | 413.028S | 61172P8 | 2035-04-01 | decoded |
| 13 | 413.050S | 40045P6 | 2034-11-01 | decoded |
| 14 | 413.026S | 6889P71 | 2033-07-01 | decoded |
| 15 | 413.035S | 95663P8 | 2036-01-01 | decoded |
| 16 | 413.026S | 281402P | 2036-06-01 | decoded |

Reference aggregation: 16 physical pieces -> 15 REF/lot/expiry combinations.
Labels 5 and 6 produce quantity 2, never a duplicate-identity error.

## Read-only Supabase verification

The deployed inventory schema and old RPC were inspected. A read-only query found
14 of the 15 reference lot combinations in MAG1; 413.026S/6889P71 was not returned.
All returned expiries were NULL. Eleven combinations had quantity zero; the remaining
three were 413.026S/281402P (2), 413.035S/95663P8 (2), 413.040S/62405P5 (3).
These are observations at query time, not permission to repair historical data.
The new strict path blocks these records until inventory is independently reconciled.

## Tests and limits

- 34 dedicated Python tests: physical duplicates 2/3, distinct lots, overlapping
  crops, artificial duplicate IDs, incomplete REF, GTIN confusion, invalid quantities,
  missing count/review, inventory identity/expiry, failed reads and 16 crop regressions.
- Each fixture's GS1 lot/expiry is independently checked against printed reference
  values; original and 180-degree crop variants decode identically.
- Wider Python smoke/API/access/deployment/document suites run separately.
- Dependency check exposed an existing multidict 7/aiohttp incompatibility; both
  lockfiles now use multidict 6.6.4.
- No OpenAI key is present in this execution environment. Live localization and REF
  OCR on the whole original PDF have NOT been proven. Geometry detection remains
  probabilistic and requires the operator count check. No autonomous count is trusted.
- Low-quality/partial labels require manual correction or a separate sharper photo.
  The current editor intentionally does not allow fabricated additional physical IDs.
- Mobile API gets the new extraction metadata, but its editor/RPC has not been
  migrated to per-label review. Production activation must account for that remaining
  integration; this change does not claim mobile save parity.

## Release gate

1. Run `ENABLE_AI_OCR=true python tools/verify_santa_lucia.py /path/to/original.pdf`
   with the production OCR model and a securely configured OpenAI key. The command
   verifies geometry matching AND each REF/lot/expiry, not simply 16 output rows.
   Any missing, mixed, duplicated or incorrect label fails the run.
2. Exercise actual Streamlit operator review in staging with read-only inventory;
   verify missing count/unchecked labels/unknown lots/null expiries cannot save.
3. Run isolated SQL regression tests and review service-role-only permissions.
4. Deploy `sql/verified_physical_label_discharge.sql` before the Streamlit change.
   The new UI fails closed if its RPC is absent. No historical stock update is needed.
5. Complete the mobile per-label review path before claiming parity across clients.
6. Publish after the live test and staging checks pass. Do not discharge the original
   reference document as a test, and do not auto-fill historical NULL expiry values.
