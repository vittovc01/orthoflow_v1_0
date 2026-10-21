# Scarico Sala AI: GPT-5.4 mini

The user explicitly requested a GPT-5.4 mini cost policy. `ai_status.label_model`
is now `gpt-5.4-mini`, regardless of a legacy `SCARICO_FULL_PAGE_MODEL` secret.
No provider failure upgrades the reader to Astra or GPT-5.4. DDT keeps its separate
model setting. Existing extracted reviews remain usable; this change does not
force a paid reanalysis or change the physical-label contract version.

## Preserved reading contract

- Two independent whole-page reads, overlapping with the same bounded workers.
- Same prompts, strict JSON output, stable pass order, label matching, REF suffix
  checks, LOT/expiry conflict handling and preservation of repeated physical labels.
- Same optional local barcode evidence, manual editing and final human confirmation.
- Stock validation, idempotence, archives and hospital ownership are unchanged.

Mini uses `detail=original`, reasoning effort `low`, and explicit preprocessing
within its documented 10,000-patch / 6,000-pixel limits. Native scans below these
limits are preserved. Larger pages are proportionally resized as a whole; no
preliminary label crop replaces the input. The representative CamScanner native
size 2448x3316 is below these limits and stays unchanged.

Official compatibility references checked 2026-10-21:
- https://developers.openai.com/api/docs/models/gpt-5.4-mini
- https://developers.openai.com/api/docs/guides/images-vision

## Consumption

Provider-reported usage is retained for each completed read, including responses
that cannot be parsed as labels. Errors carry the known billed usage to the
caller. Multi-document results preserve document index, and duplicate documents
never duplicate usage. No photograph, prompt, response text or credential enters
these consumption records.

The app thread inserts a batch into the existing `ocr_usage` table after each
analyzed document. Workers never access Streamlit session state. A telemetry
outage does not retry the AI or discard labels. Known consumption also appears
with the current review and a USD cost estimate is shown in Scarico Sala AI.

Standard rates checked 2026-10-21: mini input $0.75, cached input $0.075,
output $4.50 per million tokens. Reasoning tokens already included in output are
not added again. Unknown/missing usage is not represented as free processing.
These are estimates for reported usage, excluding tax, custom pricing and other
billing adjustments, not provider invoices. No database schema/grant change.

## Validation and limitation

233 local Python tests passed, including the real application entry point with
synthetic provider responses, stale Astra secrets, original-detail options,
both independent reads, consensus, 404 without upgrade, consumption math,
failed parsing, duplicate-document accounting, batch telemetry and editor/RPC
regressions. No paid AI call and no production stock test write were made.

This verifies the routing and reading logic, not mini's recognition accuracy on
real documents. The first real mini analysis still requires comparison against
all physical labels. The user-facing final review remains required.
