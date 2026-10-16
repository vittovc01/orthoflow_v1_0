from datetime import date
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PIL import Image
from ocr_review import assess_label, aggregate_review, normalize_expiry, validate_confirmation
from ocr_repository import OriginalDocument, SupabaseReviewRepository
from ocr_service import analyze_documents


def row(label='one',lot='LOT'):
    return {'label_id':label,'code':'413.040S','lot':lot,'expiry':'2035-04-01',
            'description':'screw','gtin':None,'quantity':1,'reviewed':True}


@pytest.mark.parametrize('raw,expected,precision',[
    ('01/04/2035','2035-04-01','day'),('2035-04-01','2035-04-01','day'),
    ('02/2036','2036-02-29','month'),('31/02/2036',None,None)])
def test_dates_preserve_month_precision(raw,expected,precision):
    assert normalize_expiry(raw)==(expected,precision)


def test_barcode_conflict_never_silently_corrects_printed_lot():
    item=row(); item['barcodes']=[{'raw':'(01)07611819268623(17)350401(10)OTHER'}]
    item['ocr_reads']=[row(),row()]
    result=assess_label(item,today=date(2030,1,1))
    assert result['fields']['lot']['status']=='conflict'
    assert result['fields']['lot']['value'] is None
    assert result['fields']['lot']['observations']['datamatrix']==['OTHER']
    assert result['needs_review']


def test_field_methods_are_distinct_and_missing_ref_is_not_gtin():
    item=row();item.update(code=None,gtin='07611819268623',lot='LOT',
                         barcodes=[{'raw':'(01)07611819268623(17)350401(10)LOT'}])
    fields=assess_label(item)['fields']
    assert fields['code']['value'] is None
    assert fields['code']['status']=='missing'
    assert fields['lot']['method']=='datamatrix'
    assert fields['gtin']['method']=='datamatrix'
    assert fields['description']['method']=='ocr'


@pytest.mark.parametrize('today,status',[(date(2036,1,1),'expired'),(date(2035,3,1),'soon'),(date(2034,1,1),'valid')])
def test_expiry_alerts(today,status):
    assert assess_label(row(),today=today)['expiry_status']==status


def test_catalogue_mismatch_and_clipped_border_are_explicit():
    item=row();item['bbox']=[0,10,1000,300]
    result=assess_label(item,catalog={'413.041S'})
    assert result['fields']['code']['status']=='unknown_catalogue'
    assert any('bordo' in s for s in result['issues'])
    assert assess_label(row(),catalog={'413040S'})['fields']['code']['status']!='unknown_catalogue'


def test_aggregation_exact_ref_lot_and_conflicting_expiry():
    groups=aggregate_review([row('1'),row('2'),row('3','OTHER')])
    assert len(groups)==2 and groups[0]['quantity']==2
    other=row('2');other['expiry']='2035-05-01'
    with pytest.raises(ValueError,match='Scadenze discordanti'):
        aggregate_review([row(),other])
    with pytest.raises(ValueError,match='ripetuta'):
        aggregate_review([row(),row()])


def test_confirmation_requires_real_count_review_identity_and_one_piece():
    item=row();extraction={'items':[item]}
    assert validate_confirmation(extraction,[item],physical_count=1,count_verified=True,actor='operator')
    for kwargs in ({'physical_count':2},{'count_verified':False},{'actor':''}):
        options=dict(physical_count=1,count_verified=True,actor='operator');options.update(kwargs)
        with pytest.raises(ValueError):validate_confirmation(extraction,[item],**options)
    item['quantity']=2
    with pytest.raises(ValueError,match='solo pezzo'):
        validate_confirmation(extraction,[item],physical_count=1,count_verified=True,actor='operator')


class FakeClient:
    def __init__(self,timeout_after_insert=False):
        self.records={};self.objects={};self.writes=0;self.timeout_after_insert=timeout_after_insert
        self.storage=SimpleNamespace(from_=lambda _:self)
    def table(self,_):return self
    def select(self,_):return self
    def eq(self,_,value):self.selected=value;return self
    def limit(self,_):return self
    def insert(self,record):self.pending=record;return self
    def execute(self):
        if hasattr(self,'pending'):
            record=self.pending;del self.pending;self.records[record['id']]=record;self.writes+=1
            if self.timeout_after_insert:raise TimeoutError('committed but response lost')
            return SimpleNamespace(data=[record])
        return SimpleNamespace(data=[self.records[self.selected]] if self.selected in self.records else [])
    def upload(self,path,content,file_options):
        if path in self.objects:raise RuntimeError('duplicate')
        self.objects[path]=content;self.writes+=1
    def download(self,path):return self.objects[path]


def original():
    data=BytesIO();Image.new('RGB',(30,20),'white').save(data,format='PNG')
    return OriginalDocument('source.png',data.getvalue())


def arguments():
    return dict(request_id=str(uuid4()),actor='operator',extraction={'items':[row()],
                'pipeline_version':'test'},confirmed=[row()],documents=[original()],
                physical_count=1,count_verified=True,explicitly_confirmed=True)


def test_no_confirmation_means_zero_storage_and_database_writes():
    client=FakeClient();args=arguments();args['explicitly_confirmed']=False
    with pytest.raises(ValueError):SupabaseReviewRepository(client).save_confirmed(**args)
    assert client.writes==0


def test_immutable_originals_idempotency_and_manual_field_trace():
    client=FakeClient();repo=SupabaseReviewRepository(client);args=arguments()
    args['confirmed'][0]['lot']='CORRECTED'
    result=repo.save_confirmed(**args)
    assert result['extracted']['items'][0]['lot']=='LOT'
    assert result['confirmed'][0]['lot']=='CORRECTED'
    assert result['confirmed'][0]['confirmed_methods']['lot']=='manual'
    assert list(client.objects.values())==[original().content]
    assert repo.save_confirmed(**args)==result
    assert client.writes==2
    args['confirmed'][0]['lot']='DIFFERENT'
    with pytest.raises(ValueError,match='dati diversi'):repo.save_confirmed(**args)
    assert client.writes==2


def test_timeout_after_database_commit_does_not_duplicate_archive():
    client=FakeClient(timeout_after_insert=True);args=arguments()
    saved=SupabaseReviewRepository(client).save_confirmed(**args)
    assert saved['id']==args['request_id'] and client.writes==2


def test_different_source_file_cannot_be_attached_to_label_evidence():
    client=FakeClient();args=arguments();args['extraction']['items'][0]['source_document']='wrong'
    with pytest.raises(ValueError,match='diverso'):SupabaseReviewRepository(client).save_confirmed(**args)
    assert client.writes==0


def test_service_returns_partial_error_without_raising_or_saving():
    def analyzer(path,mode):
        assert mode=='scarico_sala'
        if path.endswith('01.png'):raise RuntimeError('reader offline')
        return {'items':[row()],'pipeline_version':'test'}
    result=analyze_documents([original(),original()],analyzer=analyzer)
    assert len(result['items'])==1 and result['documents'][1]['status']=='failed'
    assert result['detection_warnings'] and result['review_required']


def test_editor_keeps_hidden_gtin_and_rejects_forged_provenance():
    from ocr_review import merge_confirmed_fields
    source=dict(row(),gtin='07611819268623',source_document='original',barcodes=[{'raw':'evidence'}])
    edited={'label_id':'one','codice':'413.042S','lotto':'CORRECTED',
            'source_document':'forged','barcodes':[],'verificata':True}
    result=merge_confirmed_fields([source],[edited])[0]
    assert result['gtin']==source['gtin'] and result['source_document']=='original'
    assert result['barcodes']==source['barcodes']
    assert result['code']==result['codice']=='413.042S'
    assert result['lot']==result['lotto']=='CORRECTED'
    with pytest.raises(ValueError):merge_confirmed_fields([source],[dict(edited,label_id='other')])


def test_gtin_catalog_compares_mapping_not_partial_scanner_membership():
    from ocr_review import assess_label,build_review
    row={'label_id':'x','code':'413.040S','gtin':'07611819268623','lot':'A','expiry':'2035-04-01'}
    result=assess_label(row,catalog={'07611819268623':'413.041S'})
    assert result['fields']['code']['status']=='conflict'
    assert result['fields']['code']['value']=='413.040S'
    assert result['needs_review']
    result=build_review({'items':[row]},catalog={})
    assert result['missing_gtins']==[{'label_id':'x','gtin':'07611819268623','reason':'non_in_catalogo'}]
    result=build_review({'items':[dict(row,gtin=None)]},catalog={})
    assert result['missing_gtins'][0]['reason']=='assente'
