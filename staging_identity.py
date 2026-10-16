"""Fail closed when a test deployment claims to use hosted staging."""
from catalog_import import staging_project


def verify_staging(url, expected_ref, marker):
    reference=staging_project(url,expected_ref)
    if not str(url).startswith('https://') or marker!='staging':
        raise ValueError('Staging non verificato: controllare progetto e marcatore database')
    return reference
