"""Local-only browser fixture: fake prices and simulated remote read latency."""
from copy import deepcopy
import json
import runpy
from collections import Counter
from time import sleep
import streamlit as st
import supabase
from tests.test_tab_verified_prices import PricesBackend

class TimedBackend(PricesBackend):
    def execute(self):
        sleep(.15)
        return super().execute()
    def rpc(self,name,args):
        call=super().rpc(name,args)
        class Query:
            def execute(inner):
                sleep(.15)
                existing=self.data.get('tab_prezzi_verificati',[])
                result=call.execute()
                fresh=self.data['tab_prezzi_verificati'][0]
                fresh['id']=len(self.writes)
                self.data['tab_prezzi_verificati']=existing+[fresh]
                # Simulate cache expiry while the user is checking a price.
                from tab_management_ui import tab_records,base_catalogs
                tab_records.clear();base_catalogs.clear()
                return result
        return Query()

@st.cache_resource
def backend():
    value=TimedBackend();value.data['offerte_prezzi']=[]
    lines=value.data['jj_recon_records'][2]['payload']['lines']
    lines.append({**deepcopy(lines[0]),'key':'R2','ref':'Z2','lot':'L2'})
    return value

b=backend();supabase.create_client=lambda *a,**kw:b
st.session_state.update(user='test',ruolo='Admin',permessi=['DIREZIONE'])
st.session_state['full_runs']=st.session_state.get('full_runs',0)+1
runpy.run_path('pages/14_Anomalie_Prezzi.py',run_name='__main__')

@st.fragment
def diagnostics():
    st.button('Leggi statistiche test')
    st.text_area('Statistiche test',value=json.dumps({'reads':dict(Counter(b.reads)),
      'writes':len(b.writes),'full_runs':st.session_state['full_runs']}),disabled=True)
diagnostics()
