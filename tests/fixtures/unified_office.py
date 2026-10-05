"""Actual office UI and session bootstrap, with synthetic users and no live DB."""
import runpy
import supabase
from mobile.office_app import bootstrap
from tests.fixtures.mobile_backend import Backend, user
from tests.test_pages_smoke import ReadOnlyBackend

class OfficeBackend(Backend):
    def __init__(self):
        super().__init__()
        self.tables['utenti_app'].append(user(4,'direzione',['DIREZIONE']))
        for row in self.tables['utenti_app']:
            row['created_at']='2026-10-01T09:00:00Z'
    def table(self,name):
        return super().table(name) if name=='utenti_app' else ReadOnlyBackend().table(name)

backend=OfficeBackend()
supabase.create_client=lambda *a,**kw:backend
bootstrap(backend)
runpy.run_path('app.py',run_name='__main__')
