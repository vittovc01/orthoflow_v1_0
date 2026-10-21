import ast,copy,re
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scarico_workflow import reset_destination, destination_errors
from review_editor import canonical_values, apply_review_edits, row_errors
from review_exports import review_csv, review_xlsx
from datetime import date
from types import SimpleNamespace
import pandas as pd
s=Path('pages/_05_Scarico_Sala_AI_impl.py').read_text(); tree=ast.parse(s)
clean=lambda v:'' if v is None or (isinstance(v,float) and pd.isna(v)) else str(v).strip()
ns={'canonical_values':canonical_values,'reset_destination':reset_destination,'destination_errors':destination_errors,'clean':clean,'ncode':lambda v:re.sub('[^A-Z0-9]','',str(v or '').upper())}; f=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='is_other_manufacturer')
exec(compile(ast.Module(body=[f],type_ignores=[]),'filter','exec'),ns)
assert all(not ns['is_other_manufacturer'](v) for v in ['Johnson & Johnson','J&J MedTech','DePuy Synthes','NON LETTO','',None])
assert all(ns['is_other_manufacturer'](v) for v in ['Stryker','Zimmer Biomet','Medtronic','B. Braun','Smith & Nephew'])
class Context:
 def __enter__(self):return self
 def __exit__(self,*a):pass
 def download_button(self,*a,**kw):
  assert kw['data'] and kw['on_click']=='ignore'
class ST:
 def __init__(self,rows):
  self.session_state={'scarico_ai_rows':rows,'scarico_editor_revision':7};self.active=False
  self.column_config=SimpleNamespace(CheckboxColumn=lambda *a,**kw:None, TextColumn=lambda *a,**kw:None, NumberColumn=lambda *a,**kw:None)
 def fragment(self,fn):return fn
 def form(self,*a):
  outer=self
  class Form(Context):
   def __enter__(self):outer.active=True
   def __exit__(self,*a):outer.active=False
  return Form()
 def data_editor(self,df,**kw):
  assert not self.active and kw['key'].endswith('_7')
  edited=df.copy();edited.loc[edited.index[0],'conto_deposito_struttura']=True
  return edited
 def multiselect(self,*a,**kw):return []
 def selectbox(self,label,options,**kw):return options[0]
 def checkbox(self,*a,**kw):return True
 def form_submit_button(self,*a,**kw):
  assert self.active
  if a[0].startswith('Conferma e archivia'):
   assert kw['disabled'];return False
  assert not kw['disabled'];return True
 def columns(self,n):return [Context() for _ in range(n)]
 def date_input(self,*a,**kw):return kw['value']
 def text_input(self,*a,**kw):return kw.get('value','')
 def expander(self,*a,**kw):return Context()
 def __getattr__(self,name):return lambda *a,**kw:None
rows=[{'codice':'1504-00-126','lotto':'A','quantita':1,'produttore':'Synthes'},{'codice':'FOREIGN','lotto':'B','quantita':1,'produttore':'Stryker'}]; base=copy.deepcopy(rows)
ns.update({'pd':pd,'st':ST(rows),'date':date,'client_options':lambda:[{'codice_cliente':'9010013','descrizione':'MALZONI','label':'MALZONI'}],'warehouse_labels':lambda:['MAG1 - MAG1'],'agent_options':lambda:['AGENT'],'secret':lambda name,default=None:default})
# This isolated AST fragment omits the page imports and native-method binding.
ns['form_submit_button']=ns['st'].form_submit_button
ns.update(review_csv=review_csv, review_xlsx=review_xlsx)
start=next(i for i,n in enumerate(tree.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='meta' for t in n.targets))
end=next(i for i,n in enumerate(tree.body) if isinstance(n,ast.If) and isinstance(n.test,ast.BoolOp) and any(isinstance(v,ast.Name) and v.id=='confirm' for v in n.test.values))
for _ in range(2):
 exec(compile(ast.Module(body=tree.body[start:end],type_ignores=[]),'form','exec'),ns)
 assert rows==base
 assert len(ns['edited'])==1 and bool(ns['edited'].iloc[0]['conto_deposito_struttura'])
exec(compile(ast.Module(body=tree.body[end].body[:next(i+1 for i,n in enumerate(tree.body[end].body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='final_rows' for t in n.targets))],type_ignores=[]),'submit','exec'),ns)
assert ns['final_rows'][0]['conto_deposito_struttura']==True and len(ns['final_rows'])==1
print('PASS: stable source across reruns, editor outside submit form, Smart Track submitted, other brands excluded, unknown brands preserved')


# Replay only the isolated material fragment: repeated ownership toggles must
# persist/audit without asking Streamlit for any full-app rerun.
class FragmentST(ST):
 def __init__(self,source):
  super().__init__(copy.deepcopy(source));self.flags=[False,False]
 def data_editor(self,df,**kw):
  frame=df.data.copy() if hasattr(df,"data") else df.copy()
  for position,value in enumerate(self.flags):
   frame.loc[frame.index[position],"conto_deposito_struttura"]=value
  return frame
 def rerun(self,*a,**kw):
  raise AssertionError("ownership checkbox triggered full-page rerun")
physical=[canonical_values(dict(label_id=f"label-{i}",codice="1504-00-126",
 lotto=f"LOT{i}",scadenza="2035-01-01",quantita=1,produttore="Synthes")) for i in range(2)]
physical_base=copy.deepcopy(physical)
fragment_st=FragmentST(physical)
ns.update(st=fragment_st,rows=physical,source_rows=physical,is_physical_ai=True,is_malzoni=True,
          selected_client={"codice_cliente":"9010013"},user=lambda:"ci-user",
          apply_review_edits=apply_review_edits,row_errors=row_errors)
fragment=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="render_material_editor")
exec(compile(ast.Module(body=[fragment],type_ignores=[]),"fragment","exec"),ns)
for flags,log_count in [([True,False],1),([True,True],2),([True,True],2),([False,True],3)]:
 fragment_st.flags=flags
 result=ns["render_material_editor"]()
 assert result["conto_deposito_struttura"].tolist()==flags
 assert [r["conto_deposito_struttura"] for r in fragment_st.session_state["scarico_ai_rows"]]==flags
 assert len(fragment_st.session_state["scarico_correction_log"])==log_count
 assert fragment_st.session_state["scarico_editor_revision"]==7
assert physical==physical_base
logs=fragment_st.session_state["scarico_correction_log"]
assert all(l["field"]=="conto_deposito_struttura" and l["user"]=="ci-user" for l in logs)
assert logs[-1]["original"] is True and logs[-1]["corrected"] is False
print("PASS: checkbox fragment keeps its baseline, persists toggles and audits once without a full-page rerun")
