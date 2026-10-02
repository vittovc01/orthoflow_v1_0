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

## Inventory correction (2026-10-02)
The double update was reproduced and corrected. The flexible AI RPC directly debits the matched stock row; its exact audit movement (SCARICO, SCARICO SALA AI, INTERVENTO, note Scarico sala AI flessibile) now bypasses the movement trigger's additional debit. Other movement types keep the existing trigger behavior.
A guarded transaction removed 16 artificial negative stock rows totaling -17 units. Each row was checked against its exact original AI movement balance. Real stock quantities were left unchanged, all 17 movements retained, and full removed-row snapshots stored in Audit Log under AI_DOUBLE_DEBIT_20261002.
Rollback regression tests passed before and after deployment: single debit with normalized/dashed codes, repeated debits, structure stock/revenue, insufficient-stock anomalies, standard load and correction movements.
Operational monitoring must keep that exact movement marker aligned with the flexible AI RPC; if that RPC is refactored, preserve the single-writer stock contract.

## Validation
- Both edited Python files parse.
- Rollback database regression covers coordinated deletion, returned document metadata, audit snapshot, repeated-delete rejection, unchanged stock totals and execution restrictions for anon/authenticated.
- No real intervention was deleted by the validation.
