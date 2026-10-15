# OCR crop audit — 15 October 2026

Screenshots show a clinical-record header accepted as a product label and a crop
containing parts of neighbouring Synthes labels. These demonstrate geometry errors;
they do not provide the original full-resolution document for an end-to-end OCR test.

The pipeline now asks for an independent review of proposed rectangles drawn on the
source page, alongside the unmarked source. This review returns the complete corrected
label list before any identity extraction. Audit failure preserves the first detector
result with an explicit warning and leaves physical-count verification required.

Linear barcode localization now refines only unambiguous one-to-one overlaps. It
preserves visual proposals missing from the local detector and adds disjoint local
observations. A local rectangle spanning multiple visual labels cannot replace them.
Mixed layouts can use linear anchors without applying Synthes template offsets.
Local barcode localization timeouts fall back to visual crops with a warning.

Every physical label still has its own immutable observation ID. Identical REF/lot/
expiry observations at different positions aggregate to quantity 2 (or the physical
count). Different expiry dates remain separate. REF suffixes are never synthesized;
OCR disagreement still requires operator review. Inventory/anomaly behavior is unchanged.

Validation includes missing fourth sticker, spanning local crops, disjoint local
observations, and a mocked end-to-end audit replacing a header with two physical
labels that aggregate to quantity 2. Existing real-image barcode and geometry
regressions also run. The mock establishes orchestration, not model accuracy.

No OpenAI key is configured in this execution environment. Live whole-document
localization, exact REF transcription, and production deployment have not been verified.
The additional model request adds latency and usage per page. Physical count and
per-label operator review remain necessary; the audit cannot guarantee perfect OCR.
