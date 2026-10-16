# Product-region gate and privacy boundary

The local gate runs before remote localization or reading. It measures light
sticker rectangles on gray paper, uses barcode/printed product evidence, rejects
clinical/form/signature bands from local full-page OCR, and sends only a canvas
containing approved product pixels. Missing local dependencies fail closed.
Remote procedure-header extraction is removed. The operator enters procedure
metadata manually. Old pre-gate session previews are invalidated.

Candidate regions without product evidence remain in the collapsed **Regioni
scartate** panel only after privacy checks. Recovering one creates an unverified
manual observation tied to the original source digest and page. The operator
must fill and verify the product fields and physical count. A generic manual
addition no longer stores a photograph of the entire page in its evidence.

The UI OCR review archive is disabled, even with a legacy enabled flag. The
post-intervention original-document upload is skipped for AI discharges. No
archive schema, storage bucket or production stock record was changed in this
work. Upload processing still uses temporary local originals as analysis inputs.

## GTIN catalogue

The UI reads `articoli_gtin(gtin, ref)` using its existing server-side permission.
It never falls back to the partial scanner registration table. GTIN/REF conflicts
are displayed without replacing the printed REF. Absent GTINs and GTINs missing
from the catalogue remain review items and appear in a session register that can
be exported to CSV. This register is not a durable database archive. The deployed
table was read-only checked: RLS enabled, server SELECT available, zero rows.
No catalogue import or production schema change was performed.

## Evaluation

`python scripts/evaluate_ocr.py --input '<original PDF>'`

The original Federico PDF: previous local finder 0/7, new gate 7/7, new extra
regions 0. The screenshot separately proves at least one historical AI false
positive (l3); the complete historical AI response is unavailable. We do not
rerun the previous unsafe full-page remote analysis to invent a baseline.

The committed deidentified regression fixture (all clinical header and footer
pixels removed) gives the following reproducible **local geometry** comparison:

| Detector | Extra regions | True stickers found | Recall |
|---|---:|---:|---:|
| Previous local finder | 1 | 4/7 | 57.1% |
| Product gate | 0 | 7/7 | 100% |

Deidentification changes background contours, so the fixture baseline differs
from the original PDF baseline. Both JSON reports are committed separately.
Neither result measures end-to-end REF/lot/expiry transcription accuracy.

Tests intercept every model image, inject an adversarial header proposal, spy on
crop coordinates, and check returned previews and rejected regions. The fixture
contains only product labels; synthetic clinical canaries are created at test
runtime. Additional regressions retain VELYS 6/6, ATTUNE 5/5, Atripalda 4/4 and
mixed-angle Synthes 7/7. These are measured cases, not a universal recall promise
for unseen document layouts. Original count confirmation remains mandatory.
