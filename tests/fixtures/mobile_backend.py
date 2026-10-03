"""Synthetic backend for isolated API and browser tests."""
from copy import deepcopy
from types import SimpleNamespace
from datetime import date
import hashlib


def user(uid, username, permissions, agent=''):
    salt='test-salt'
    return dict(id=uid,username=username,nome_completo=username.title(),password_salt=salt,
        password_hash=hashlib.pbkdf2_hmac('sha256',b'test-password',salt.encode(),210000).hex(),
        attivo=True,stato_accesso='APPROVATO',ruolo='Corriere' if 'CORRIERE' in permissions else 'Agente',
        permessi=permissions,agente_nome=agent)


class Backend:
    def __init__(self):
        self.tables={
            'utenti_app':[user(1,'mario',['CORRIERE']),user(2,'luigi',['CORRIERE']),user(3,'agente',['AGENTE'],'Agente Test')],
            'corrieri':[dict(id=11,user_id=1,attivo=True),dict(id=12,user_id=2,attivo=True)],
            'missioni_corrieri':[
                dict(id=101,codice='M-101',data_missione=date.today().isoformat(),tipo='CONSEGNA',stato='PROGRAMMATA',corriere_id=11,struttura_id=21,kit_codice='KIT-TRAUMA',colli=2),
                dict(id=102,codice='M-102',data_missione=date.today().isoformat(),tipo='RITIRO',stato='PROGRAMMATA',corriere_id=12,struttura_id=22,kit_codice='KIT-PROTESICA',colli=1)],
            'strutture_logistiche':[dict(id=21,nome='Ospedale Demo',indirizzo='Via Esempio 1',note_consegna='Ingresso logistica'),dict(id=22,nome='Struttura Demo Due')],
            'clienti':[dict(codice_cliente='9010013',descrizione='Malzoni Demo',agente='Agente Test'),dict(codice_cliente='other',descrizione='Altra struttura',agente='Altro agente')],
            'magazzini':[dict(codice_magazzino='MAG1',nome_magazzino='Magazzino principale')],
            'offerte_clienti':[], 'foto_missioni':[], 'documenti_missioni':[], 'documenti_impianto':[],
            'orthoflow_mobile_operations':[], 'interventi':[]}
        self.calls=[]
        self.storage=Storage()

    def table(self,name): return Query(self,name)
    def rpc(self,name,payload):
        self.calls.append((name,deepcopy(payload)))
        data=[dict(codice_normalizzato='150400126',prezzo=145.0)] if name=='prezzi_manuali_struttura' else {'ok':True}
        return SimpleNamespace(execute=lambda:SimpleNamespace(data=data))


class Query:
    def __init__(self,backend,name):self.backend=backend;self.name=name;self.filters=[];self.action='select';self.payload=None
    def select(self,*args):return self
    def eq(self,k,v):self.filters.append(lambda r:r.get(k)==v);return self
    def in_(self,k,v):self.filters.append(lambda r:r.get(k) in v);return self
    def order(self,*args,**kwargs):return self
    def limit(self,*args):return self
    def range(self,*args):return self
    def insert(self,p):self.action='insert';self.payload=p;return self
    def execute(self):
        if self.action=='insert':self.backend.tables[self.name].append(self.payload);return SimpleNamespace(data=[self.payload])
        return SimpleNamespace(data=[deepcopy(r) for r in self.backend.tables.get(self.name,[]) if all(f(r) for f in self.filters)])


class Storage:
    def __init__(self):self.uploads=[];self.removed=[]
    def from_(self,*args):return self
    def upload(self,path,data,options):self.uploads.append(path)
    def remove(self,paths):self.removed.extend(paths)
    def create_signed_url(self,path,expires):return {'signedURL':'https://example.invalid/file'}
