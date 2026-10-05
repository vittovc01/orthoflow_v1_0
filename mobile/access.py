"""One account and one revocable session for the app and its office modules."""
import os
from pathlib import Path

from fastapi import HTTPException
from mobile.security import Sessions, fingerprint
from mobile.service import allowed, rows

COOKIE = 'orthoflow_mobile'
USER_COLUMNS = 'id,username,nome_completo,ruolo,permessi,agente_nome,attivo,stato_accesso,password_hash'


def session_file():
    return Path(os.getenv('MOBILE_DATA_DIR', '/tmp/orthoflow-mobile')) / 'sessions.sqlite'


def authenticated(token, sessions, backend):
    session = sessions.get(token)
    if not session:
        raise HTTPException(401, 'Accedi per continuare.')
    found = rows(backend.table('utenti_app').select(USER_COLUMNS).eq('id', session[0]).limit(1))
    if not found or not found[0].get('attivo') or found[0].get('stato_accesso') != 'APPROVATO' or fingerprint(found[0]) != session[1]:
        sessions.revoke(token)
        raise HTTPException(401, 'Sessione non più valida. Accedi nuovamente.')
    return found[0]


# No arbitrary URL/table names: this catalog also drives the visible app menu.
MODULES = [
    ('ddt-carico-mobile', 'DDT e carichi', 'LOGISTICA', 'Magazzino', 'Foto, PDF e carichi di materiale'),
    ('wms', 'Scanner e WMS', 'LOGISTICA', 'Magazzino', 'Scansiona e movimenta il materiale'),
    ('gestione-scaffale', 'Scaffali e giacenze', 'LOGISTICA', 'Magazzino', 'Ubicazioni, lotti e disponibilità'),
    ('qr-scaffali', 'QR scaffali', 'LOGISTICA', 'Magazzino', 'Etichette e identificazione scaffali'),
    ('gestione-interventi', 'Gestione interventi', 'AMMINISTRAZIONE', 'Amministrazione', 'Righe, prezzi e archivio impianti'),
    ('work-implant', 'Work Implant', 'AMMINISTRAZIONE', 'Amministrazione', 'Documenti degli impianti'),
    ('customer-connect', 'Customer Connect', 'AMMINISTRAZIONE', 'Amministrazione', 'Reintegri e rapporti con J&J'),
    ('controllo-ordini-jj', 'Controllo ordini J&J', 'AMMINISTRAZIONE', 'Amministrazione', 'Verifica ordini e fatturazione'),
    ('documenti-logistica', 'Documenti logistica', 'LOGISTICA', 'Logistica', 'Foto e certificazioni archiviate'),
    ('corrieri', 'Organizzazione corrieri', 'LOGISTICA', 'Logistica', 'Pianifica missioni, consegne e ritiri'),
    ('gestionale', 'Controlli di gestione', 'DIREZIONE', 'Direzione', 'Fatturato, inventario, offerte e anagrafiche'),
    ('anomalie-prezzi', 'Anomalie prezzi e giacenze', 'DIREZIONE', 'Direzione', 'Verifica e risolvi le anomalie'),
    ('utenti-permessi', 'Utenti e permessi', 'DIREZIONE', 'Direzione', 'Approva utenti e assegna le funzioni'),
    ('gestione-dati-corrieri', 'Archivio corrieri', 'DIREZIONE', 'Direzione', 'Gestisci lo storico logistico'),
]


def modules_for(row):
    return [dict(path=p, title=t, group=g, description=d) for p, t, perm, g, d in MODULES
            if allowed(row, perm) or (p == 'customer-connect' and allowed(row, 'AGENTE'))]


def office_allowed(row):
    return bool(modules_for(row))


def office_identity(token, backend):
    return authenticated(token, Sessions(session_file()), backend)
