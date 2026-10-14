"""Conservative clinic selection from a document header."""
import re


def clinic_default_index(clinic, clients):
    normalize=lambda v: ' '.join(re.findall(r'[A-Z0-9]+',str(v or '').upper()))
    target=normalize(clinic)
    exact=[i for i,c in enumerate(clients) if normalize(c.get('descrizione'))==target and target]
    if len(exact)==1:
        return exact[0]
    generic={'CASA','DI','CURA','PRIVATA','CLINICA','CLINIC','OSPEDALE','SPA','SRL','SRLS','S','R','L','A','P','DEL','DELLA','DEI','IL','LA','E','SAN','SANTA'}
    tokens=set(target.split())-generic
    if not tokens:
        return 0
    scored=[]
    for i,c in enumerate(clients):
        other=set(normalize(c.get('descrizione')).split())-generic
        shared=tokens & other
        if shared:
            scored.append((len(shared),len(shared)/len(tokens|other),i))
    if not scored:
        return 0
    scored.sort(reverse=True)
    if len(scored)>1 and scored[0][:2]==scored[1][:2]:
        return 0
    return scored[0][2]
