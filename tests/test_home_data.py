from datetime import date
from home_data import load_home, paginated
from tests.fixtures.home_backend import HomeBackend


def test_counts_do_not_stop_at_api_limit_and_recent_is_ordered():
    backend=HomeBackend(date(2026,10,5))
    backend.tables['interventi']=[dict(id=i,data_intervento='2026-10-05',cliente='Demo') for i in range(1205)]
    data=load_home(backend,date(2026,10,5))
    assert data['month']==1205 and data['today']==1205
    assert [r['id'] for r in data['recent']]==[1204,1203,1202,1201,1200,1199]
    assert len(paginated(backend.table('interventi').select('id').order('id')))==1205
    assert all(columns!='*' for _,columns in backend.calls)


def test_stock_anomalies_use_same_classification_as_resolution_page():
    data=load_home(HomeBackend(date(2026,10,5)),date(2026,10,5))
    # Malzoni structure-owned stock and orphaned historical alerts are excluded.
    assert data['stock_anomalies']==1
    assert data['price_anomalies']==1
    assert data['anomalies']==2


def test_errors_are_unknown_not_zero_and_independent_sections_survive():
    backend=HomeBackend(date(2026,10,5));backend.fail={'anomalie_giacenza','missioni_corrieri','giacenze'}
    data=load_home(backend,date(2026,10,5))
    assert data['stock_anomalies'] is None and data['anomalies'] is None
    assert data['missions'] is None and data['lots'] is None and data['expiring'] is None
    assert data['price_anomalies']==1 and data['recent']
    assert 'Scadenze' in data['errors']


def test_month_and_expiry_boundaries_use_operational_dates():
    backend=HomeBackend(date(2026,10,1))
    backend.tables['interventi']=[dict(id=1,data_intervento='2026-09-30'),dict(id=2,data_intervento='2026-10-01'),dict(id=3,data_intervento='2026-10-31'),dict(id=4,data_intervento='2026-11-01')]
    backend.tables['giacenze']=[dict(id=1,quantita=1,scadenza='2026-12-30'),dict(id=2,quantita=1,scadenza='2026-12-31'),dict(id=3,quantita=0,scadenza='2026-09-30'),dict(id=4,quantita=1,scadenza=None)]
    data=load_home(backend,date(2026,10,1))
    assert data['month']==2 and data['today']==1
    assert data['lots']==3
    assert [r['id'] for r in data['expiring']]==[1]
