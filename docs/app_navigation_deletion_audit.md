# OrthoFlow: navigation and intervention deletion audit

## Changes
- Removed Scarico sala, DDT carico / Loan, Work Implant and Customer Connect from the legacy inner menu. Dedicated main-navigation pages remain the canonical entry points; old quick actions redirect there.
- Intervention deletion in Gestione dati now calls service-role-only, SECURITY INVOKER RPC elimina_intervento_completo. Header, rows, implant document records, inventory anomalies and unfulfilled kit requests without DDT are deleted in one transaction.
- Completed replenishments and commercial documents remain historical records; existing FK behavior preserves/unlinks their references.
- Audit Log stores the deleted header, rows and document metadata.
- Associated Storage files are removed after database commit, retaining files referenced by another document. Failed removals are held in the current session for Riprova pulizia allegati. File cleanup is not transactionally atomic with database deletion.
- Bulk removal of interventions uses the same complete-deletion path.
- This is administrative deletion: inventory quantities and movement history remain unchanged. Cancellation with physical stock reversal requires a separate explicit flow.
- Clarified top dashboard label as Fatturato totale.

## Overlap still worth consolidating
- Controllo di Gestione dashboard and KPI e Fatturato share revenue charts, but KPI also has filters. Consolidate into one economic page retaining those filters.
- Legacy 04_DDT_Carico.py is not used by the main router; active DDT page is 04_DDT_Carico_v2.py. The legacy DDT entry is now removed/redirected, without deleting source code.
- Archive document previews also exist in raw Gestione dati. Raw data management is an administrative tool; daily document consultation should remain in Archivio impianti.
- Offer/history price helpers are duplicated in Scarico Sala AI and Gestione Interventi. A shared module can remove implementation duplication; run-scoped cache behavior must remain intact.
- One orphan implant-document record was found; no existing orphan record was deleted automatically.

## Inventory finding
The existing crea_intervento_scarico_ai_flessibile function directly decrements giacenze and also inserts a movement. An AFTER INSERT trigger independently applies that movement to giacenze under origin SCARICO SALA AI. This deserves a dedicated correction and reconciliation; these changes deliberately do not change existing stock quantities or infer corrections from historical movements.

## Validation
- Both edited Python files parse.
- Rollback database regression covers coordinated deletion, returned document metadata, audit snapshot, repeated-delete rejection, unchanged stock totals and execution restrictions for anon/authenticated.
- No real intervention was deleted by the validation.
