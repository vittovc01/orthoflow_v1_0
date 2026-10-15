# Measured sticker boundaries — 15 October 2026

The uploaded photograph contains seven distinct Synthes stickers. Before this
change, the local finder located seven symbols, including a wrong cardinal
orientation for the inclined, partly clipped right sticker. The selector discarded
all local geometry whenever the visual model returned a different label count.

The shared geometry pipeline now measures bright sticker rectangles around finder
anchors across conservative intensity thresholds. Each accepted rectangle must
contain exactly one physical finder, satisfy size/aspect/rectangularity limits,
and belong to a set of at least three measured stickers. The long edge controls
orientation and residual deskew. Partial segmentation at the REF end is extended
only within the measured sticker family. No identifiers are inferred from geometry.

For the supported Synthes layout, a fully measured physical set survives a visual
count disagreement. Additional disjoint visual proposals require independent REF
or GS1 evidence. Unconfirmed proposals remain in extraction metadata and are shown
in a separate UI expander for operator inspection rather than silently discarded.
Other layouts retain their existing geometry path. Physical count and individual
review remain required. The UI displays the extraction version and provides a
reanalysis button for stale results, without automatically overwriting corrections.

Regression fixture contains only the product-label area, excluding the patient,
clinical record and clinical header. Seven independently marked printed REF areas
remain inside exactly one crop at all four cardinal orientations, including the
inclined sticker. These tests validate geometry, not live model transcription.
Existing Synthes, ATTUNE, VELYS, scanned-label and quantity regressions also apply.

Historical comparison: the pre-per-label path sent the full document to the model;
current reading depends on geometric crops. This change repairs that dependency
without reverting exact-field disagreement checks or duplicate-piece counting.
No hospital-specific coordinates, product identities or lots are used by production
code. No OpenAI secret is available here, so exact live REF/lot/expiry extraction
and production deployment still require end-to-end verification.
