import ast,copy,re
from pathlib import Path
from datetime import date
from types import SimpleNamespace
import pandas as pd
s=Path('pages/_05_Scarico_Sala_AI_impl.py').read_text(); tree=ast.parse(s)
clean=lambda v:'' if v is None or (isinstance(v,float) and pd.isna(v)) else str(v).strip()
ns={'clean':clean,'ncode':lambda v:re.sub('[^A-Z0-9]','',str(v or '').upper())}; f=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='is_other_manufacturer')
exec(compile(ast.Module(body=[f],type_ignores=[]),'filter','exec'),ns)
assert all(not ns['is_other_manufacturer'](v) for v in ['Johnson & Johnson','J&J MedTech','DePuy Synthes','NON LETTO','',None])
assert all(ns['is_other_manufacturer'](v) for v in ['Stryker','Zimmer Biomet','Medtronic','B. Braun','Smith & Nephew'])
class Context:
 def __enter__(self):return self
 def __exit__(self,*a):pass
class ST:
 def __init__(self,rows):
  self.session_state={'scarico_ai_rows':rows,'scarico_editor_revision':7};self.active=False
  self.column_config=SimpleNamespace(CheckboxColumn=lambda *a,**kw:None, TextColumn=lambda *a,**kw:None)
 def form(self,*a):
  outer=self
  class Form(Context):
   def __enter__(self):outer.active=True
   def __exit__(self,*a):outer.active=False
  return Form()
 def data_editor(self,df,**kw):
  assert self.active and kw['key'].endswith('_7')
  edited=df.copy();edited.loc[edited.index[0],'conto_deposito_struttura']=True
  return edited
 def multiselect(self,*a,**kw):return []
 def selectbox(self,label,options,**kw):return options[0]
 def checkbox(self,*a,**kw):return True
 def form_submit_button(self,*a,**kw):
  assert self.active and not kw['disabled'];return True
 def columns(self,n):return [Context() for _ in range(n)]
 def date_input(self,*a,**kw):return kw['value']
 def text_input(self,*a,**kw):return kw.get('value','')
 def expander(self,*a,**kw):return Context()
 def __getattr__(self,name):return lambda *a,**kw:None
rows=[{'codice':'1504-00-126','lotto':'A','quantita':1,'produttore':'Synthes'},{'codice':'FOREIGN','lotto':'B','quantita':1,'produttore':'Stryker'}]; base=copy.deepcopy(rows)
ns.update({'pd':pd,'st':ST(rows),'date':date,'client_options':lambda:[{'codice_cliente':'9010013','descrizione':'MALZONI','label':'MALZONI'}],'warehouse_labels':lambda:['MAG1 - MAG1'],'agent_options':lambda:['AGENT']})
start=next(i for i,n in enumerate(tree.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='meta' for t in n.targets))
end=next(i for i,n in enumerate(tree.body) if isinstance(n,ast.If) and isinstance(n.test,ast.Name) and n.test.id=='confirm')
for _ in range(2):
 exec(compile(ast.Module(body=tree.body[start:end],type_ignores=[]),'form','exec'),ns)
 assert rows==base
 assert len(ns['edited'])==1 and bool(ns['edited'].iloc[0]['conto_deposito_struttura'])
exec(compile(ast.Module(body=tree.body[end].body[:2],type_ignores=[]),'submit','exec'),ns)
assert ns['final_rows'][0]['conto_deposito_struttura']==True and len(ns['final_rows'])==1
print('PASS: stable source across reruns, editor in form, Smart Track submitted, other brands excluded, unknown brands preserved')
