"""Reproduce a Cloud worker retaining an older reconciliation dependency."""
import jj_reconciliation
import jj_runtime


def test_warm_worker_recovers_missing_bulk_and_export_entrypoints(monkeypatch):
    monkeypatch.delattr(jj_reconciliation, 'allocation_plan')
    monkeypatch.delattr(jj_reconciliation, 'confirmed_associations')
    jj_runtime._signatures.clear()
    current = jj_runtime.current_reconciliation()
    assert callable(current.allocation_plan)
    assert callable(current.confirmed_associations)
    assert current.allocation_plan([], [], 1) == []


def test_dependencies_reload_only_on_first_load_or_source_change(monkeypatch):
    reload = jj_runtime.importlib.reload
    calls = []
    def tracked(module):
        calls.append(module.__name__)
        return reload(module)
    monkeypatch.setattr(jj_runtime.importlib, 'reload', tracked)
    jj_runtime._signatures.clear()
    jj_runtime.current_reconciliation()
    assert calls == ['jj_closures', 'jj_reconciliation']
    calls.clear()
    jj_runtime.current_reconciliation()
    assert calls == []
    jj_runtime._signatures['jj_reconciliation'] = None
    jj_runtime.current_reconciliation()
    assert calls == ['jj_reconciliation']
