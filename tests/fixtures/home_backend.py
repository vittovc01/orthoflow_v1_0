"""Synthetic, read-only Home data. No live connections or patient details."""
from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo


class HomeBackend:
    def __init__(self, today=None):
        day = today or datetime.now(ZoneInfo('Europe/Rome')).date()
        self.fail = set()
        self.calls = []
        self.tables = {
            'interventi': [dict(id=i, data_intervento=(day-timedelta(days=i//3)).isoformat(),
                cliente=['Clinica Malzoni · Demo','ASL Avellino · Demo','Santa Lucia · Demo'][i % 3],
                agente=['Cillo · Demo','Camilleri · Demo'][i % 2], linea='TRAUMA', codice_cliente='9010013' if i==1 else 'TEST') for i in range(1,16)],
            'righe_intervento': [dict(id=1,intervento_id=1,codice='1504-00-126',lotto='A',origine='CONTO DEPOSITO STRUTTURA',prezzo_source='MANUALE_MEMORIZZATO'),
                dict(id=2,intervento_id=2,codice='CODE',lotto='B',origine='OCR',prezzo_source='DA_VERIFICARE_DIREZIONE')],
            'anomalie_giacenza': [dict(id=1,intervento_id=1,codice='150400126',lotto='A',stato='DA_VERIFICARE'),dict(id=2,intervento_id=2,codice='CODE',lotto='B',stato='DA_VERIFICARE'),dict(id=3,intervento_id=999,codice='OLD',lotto='',stato='DA_VERIFICARE')],
            'giacenze': [dict(id=i,codice=f'DEMO-{i:04}',lotto=f'L{i:04}',scadenza=(day+timedelta(days=(i*18)-25)).isoformat(),quantita=3,codice_magazzino='MAG01') for i in range(1,9)],
            'missioni_corrieri': [dict(id=1,codice='M-001',data_missione=day.isoformat(),tipo='CONSEGNA',stato='PROGRAMMATA',colli=2),dict(id=2,codice='M-002',data_missione=(day+timedelta(days=1)).isoformat(),tipo='RITIRO',stato='ARRIVATO',colli=1)],
            'ocr_usage': []}

    def table(self,name):
        return Query(self,name)


class Query:
    def __init__(self, backend, name):
        self.backend=backend;self.name=name;self.filters=[];self.orders=[];self.window=None;self.cap=1000;self.exact=False;self.head=False
    def select(self, columns, count=None, head=False):
        self.backend.calls.append((self.name, columns));self.exact=count=='exact';self.head=head;return self
    def eq(self,k,v):self.filters.append(lambda r:r.get(k)==v);return self
    def in_(self,k,v):self.filters.append(lambda r:r.get(k) in v);return self
    def gt(self,k,v):self.filters.append(lambda r:r.get(k) is not None and r[k]>v);return self
    def gte(self,k,v):self.filters.append(lambda r:r.get(k) is not None and r[k]>=v);return self
    def lt(self,k,v):self.filters.append(lambda r:r.get(k) is not None and r[k]<v);return self
    def lte(self,k,v):self.filters.append(lambda r:r.get(k) is not None and r[k]<=v);return self
    def order(self,k,desc=False):self.orders.append((k,desc));return self
    def limit(self,n):self.cap=n;return self
    def range(self,start,end):self.window=(start,end);return self
    def execute(self):
        if self.name in self.backend.fail:raise RuntimeError('Synthetic unavailable backend')
        values=[deepcopy(r) for r in self.backend.tables.get(self.name,[]) if all(f(r) for f in self.filters)]
        for k,desc in reversed(self.orders):values.sort(key=lambda r:r[k] if r.get(k) is not None else '',reverse=desc)
        count=len(values) if self.exact else None
        if self.head:values=[]
        elif self.window:values=values[self.window[0]:self.window[1]+1][:1000]
        else:values=values[:self.cap]
        return SimpleNamespace(data=values,count=count)
