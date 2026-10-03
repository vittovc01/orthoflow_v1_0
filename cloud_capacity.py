"""Aggregate quota display; configured quotas must follow the actual subscription."""
import os


def capacity(sb, database_limit=500_000_000, file_limit=1_000_000_000):
    result = sb.rpc('orthoflow_cloud_capacity', {}).execute().data
    result = result[0] if isinstance(result, list) else result
    limits = {'database_bytes': int(database_limit), 'file_bytes': int(file_limit)}
    if any(v <= 0 for v in limits.values()):
        raise ValueError('Cloud quotas must be positive.')
    return {**result, 'limits': limits,
            'warning': any(int(result[k]) / v >= .8 for k,v in limits.items()),
            'critical': any(int(result[k]) / v >= .95 for k,v in limits.items())}


def render_capacity(sb):
    import streamlit as st
    with st.expander('Spazio cloud e protezione dei dati'):
        try:
            def limit(name, default):
                try: return st.secrets.get(name, os.getenv(name, default))
                except Exception: return os.getenv(name, default)
            data = capacity(sb, limit('CLOUD_DATABASE_LIMIT_BYTES',500_000_000),
                            limit('CLOUD_FILE_LIMIT_BYTES',1_000_000_000))
            a,b,c=st.columns(3)
            for col,key,label in [(a,'database_bytes','Database'),(b,'file_bytes','Documenti')]:
                used=int(data[key]); total=data['limits'][key]
                col.metric(label, f'{used/1_000_000:.1f} MB / {total/1_000_000:.0f} MB')
            c.metric('File archiviati', int(data['file_count']))
            if data['critical']: st.error('Spazio cloud oltre il 95%: intervenire prima di nuovi caricamenti.')
            elif data['warning']: st.warning('Spazio cloud oltre l’80%: pianificare l’ampliamento dell’archivio.')
            else: st.success('Spazio disponibile per nuovi dati e documenti.')
            st.caption('Misura tecnica indicativa. Le quote devono seguire il piano Supabase effettivo. '
                       'Questo indicatore non certifica che i backup siano attivi: verificarne esito e ripristino.')
        except Exception:
            st.warning('Misura dello spazio non disponibile. Non è possibile confermare la capacità residua.')
