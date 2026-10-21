# Scarico Sala: bounded parallel reads and mandatory destination

Every successful fresh extraction clears both destination widgets. The customer
selector no longer matches an OCR clinic name or selects the first customer; the
line no longer defaults to TRAUMA. Successful discharge queues another reset
before the next render (Streamlit forbids mutating an already rendered widget).
Both fields are required to enable discharge; an independent Python server guard
runs before any review archive or stock write. Archive-only review still creates
no intervention and does not require an intervention destination.

## Analysis

Two independent whole-page requests now overlap, with at most two reader workers
per document and one separate local-evidence worker. Pages and documents remain
sequential, preserving the bounded PDF allocations. The model, original pixels,
JSON schema, prompts, stable pass order and conflict/multiplicity rules are kept.
Both passes use the same single encoded image. Each owns its fallback state.
A failed pass does not discard its successful sibling. Quota errors do not retry;
a provider block prevents further pages/documents. Two requests may already be
in flight when a quota error is received; this concurrency can encounter provider
limits sooner than serialized requests, without increasing the normal request count.

The catalogue lookup requests only GTINs detected on this document (batches of
200), after reading. No GTIN means no catalogue query. Unknown/missing GTINs remain
advisory. The full-catalogue loader remains available to other callers. Review
snapshots are session-local; no cross-user product, source or price cache is added.

## Confirmation

One freshly paginated stock snapshot supplies both identity and quantity previews,
instead of another request for each code/lot. Pagination advances by received
rows until empty, including server limits smaller than the requested page size.
Normalized REF matching is retained. Database locks, validation, anomaly handling
and request UUID idempotence in the authoritative RPC are unchanged.

Offer headers are fetched together while retaining link priority. Product-only
immutable archive uploads overlap with at most three workers. All uploads must
succeed or match a previous identical object before inserting the review and
allowing the stock transaction. A failed upload cannot insert a review; retries
reuse the existing paths and UUID. No original document is uploaded by this change.

## Verification

- Controlled three-run median with a synthetic 20x20 image and a fake provider
  taking 250 ms per read: previous reader **0.503 s**, parallel reader **0.253 s**.
  Identical output labels and consensus evidence. This measures scheduling only,
  not live API latency, production accuracy or end-to-end discharge time.
- For 16 distinct product/lot rows fitting one stock page: previous physical flow
  needed 17 stock requests (one snapshot + 16 checks); new flow needs 2 (data + EOF).
- For 16 offer links: 17 header/link requests become 2; priority is tested.
- Event/barrier tests prove both independent reads overlap, crops overlap before
  review insert, and failed uploads cannot commit a review.
- Real Streamlit AppTest covers empty initial choices despite an OCR clinic name,
  either missing choice disabling submit, reset after completed discharge, existing
  manual editing, expiry validation, Smart Track flags and timeout/retry UUID reuse.
- All fixtures and measurements are local/synthetic; no production stock write.

Live AI and end-to-end production timings still require a real user discharge.
