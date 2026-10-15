"""Fail-closed transport gate. The model receives approved label crops ONLY.

Approval is produced in local review by the authenticated operator, bound to
source bytes. Ground truth annotations are not an approval source.
"""
import hashlib
from pathlib import Path


def approved_regions(path,approval):
    from local_label_reader import prepare_document
    if not approval or approval.get('approved') is not True or approval.get('labels_only_confirmed') is not True:
        raise ValueError('Privacy: approvazione locale obbligatoria prima del modello')
    actual=prepare_document(path)
    if approval.get('sha256')!=actual['sha256'] or approval.get('approved') is not True or approval.get('labels_only_confirmed') is not True:
        raise ValueError('Privacy: confermare localmente i soli ritagli delle etichette prima del modello')
    from label_pipeline import unique_regions
    selected=approval.get('regions') or []
    if not selected:raise ValueError('Privacy: nessuna etichetta approvata')
    allowed={(r['page'],tuple(r['bbox']),r['rotation']) for r in actual['regions']}
    for r in selected:
        if (r['page'],tuple(r['bbox']),r['rotation']) not in allowed:
            raise ValueError('Privacy: ritaglio non corrispondente alle proposte locali del documento')
    return unique_regions(selected)
