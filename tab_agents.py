"""Business Cube agent codes explicitly confirmed by the agency.

These are source-system codes, not IDs from the OrthoFlow agent/user tables.
"""
AGENT_NAMES={
    '1':'PM Medical',
    '2':'Maurizio Guarino',
    '3':'Cristiano',
    '4':'Mariano Borrelli',
    '5':'Mariano Gargiulo',
    '6':'Assunta Mastrota',
    '7':'Francesco De Lisi',
    '8':'Francesco Cirillo',
    '9':'Giampiero',
}

def agent_name(value):
    raw='' if value is None else str(value).strip().removesuffix('.0')
    if raw.lower() in ('','nan','none','nat'):return 'Non assegnato'
    if raw.isdigit():
        code=str(int(raw))
        return 'Non assegnato' if code=='0' else AGENT_NAMES.get(code,'Codice agente '+code)
    return raw

def payload_agent(payload):
    value=payload.get('agent_code')
    if value is None or str(value).strip()=='':value=payload.get('agent') or payload.get('agente')
    return agent_name(value)
