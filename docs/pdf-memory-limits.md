# PDF raster memory

Full-page scans can use image pixel dimensions as PDF page points. Rendering
every PDF at a fixed scale of four then creates sixteen times the original
number of pixels, without adding detail to a scanned photograph.

The renderer chooses its scale before allocating a pixmap. Large full-page
scans retain their native sampling density; ordinary vector A4 pages retain
the previous scale of four (288 dpi). Other large pages are capped below
28 million pixels and the vision dimension limit. The complete page is kept.
No input is cropped or masked by this change.

The whole-page reader streams pages instead of retaining an entire rasterised
PDF. The duplicate-image fingerprint also streams pages and explicitly closes
each raster before calling the analyzer. The legacy indexed rendering API
remains available to existing callers.

For the reported one-page CamScanner document, the original scan is 2448 × 3264
pixels and the page is 2448 × 3316 points. The old renderer produced 9792 × 13264
(129,881,088 pixels); the corrected renderer produces 2448 × 3316 (8,117,568
pixels), preserving all native scan pixels and the page layout. A local process
running the corrected fingerprint and renderer peaked at 172,376 KiB RSS.
This measurement covers preparation only, not the AI service or the complete
Streamlit session. No production records were created for this measurement.

Model, prompts, original-detail requests, independent reads, matching and
review rules remain unchanged. Automated tests use synthetic PDFs without
clinical information and cover native-size scans, vector pages, allocation
limits, lazy rendering and release before analysis. Real AI transcription
accuracy must still be assessed on the live service after deployment.
