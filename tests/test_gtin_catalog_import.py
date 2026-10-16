import csv
import pytest
from catalog_import import prepare_catalog, staging_project, import_supabase_staging


def source(tmp_path, rows):
    path=tmp_path/'catalog.csv'
    with path.open('w',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['gtin','ref','categoria']);writer.writerows(rows)
    return path


def test_all_categories_and_leading_zero_retained(tmp_path):
    rows=[['00000000000017','TEST-A','Trauma'],['00000000000024','TEST-B','Other']]
    data=prepare_catalog(source(tmp_path,rows),source_version='test')
    assert len(data['rows'])==2 and data['rows'][0]['gtin']=='00000000000017'
    assert {r['categoria'] for r in data['rows']}=={'Trauma','Other'}


def test_conflicting_ref_aborts_whole_file(tmp_path):
    with pytest.raises(ValueError,match='REF discordanti'):
        prepare_catalog(source(tmp_path,[['00000000000017','A',''],['00000000000017','B','']]),source_version='test')


def test_discard_report_and_nullable_category(tmp_path):
    rows=[['00000000000017','A',''],['00000000000017','A',''],['0000000000017','A','']]
    data=prepare_catalog(source(tmp_path,rows),source_version='test')
    assert data['input_rows']==3 and len(data['rows'])==1 and len(data['discarded'])==2
    assert data['missing_categories']==1


def test_production_denied_before_client_creation():
    with pytest.raises(ValueError,match='produzione bloccata'):
        import_supabase_staging({},url='https://foawqtscqtwhpkbfbibj.supabase.co',key='unused',expected_ref='foawqtscqtwhpkbfbibj',staging_confirmed=True)
    with pytest.raises(ValueError):staging_project('https://other.supabase.co','staging')
