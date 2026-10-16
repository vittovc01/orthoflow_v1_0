import pytest
from staging_identity import verify_staging


def test_known_production_project_cannot_be_declared_staging():
    with pytest.raises(ValueError):
        verify_staging('https://foawqtscqtwhpkbfbibj.supabase.co','foawqtscqtwhpkbfbibj','staging')


@pytest.mark.parametrize('url,ref,marker',[
 ('https://separate-stage.supabase.co','separate-stage',None),
 ('https://wrong.supabase.co','separate-stage','staging'),
 ('https://separate-stage.supabase.co','','staging'),
 ('http://separate-stage.supabase.co','separate-stage','staging')])
def test_staging_requires_matching_project_https_and_database_marker(url,ref,marker):
    with pytest.raises(ValueError):verify_staging(url,ref,marker)


def test_explicit_separate_staging_is_accepted():
    assert verify_staging('https://separate-stage.supabase.co','separate-stage','staging')=='separate-stage'
