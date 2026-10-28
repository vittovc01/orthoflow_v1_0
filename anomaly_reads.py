"""Bounded reconnection for read-only anomaly queries; never wrap mutations."""

def read_rows(client_factory, query, reset_client):
    try:
        return query(client_factory()).execute().data or []
    except Exception as exc:
        # PGRST303 is JWT validation rejection. Rebuild the server client once;
        # never change credentials, weaken permissions, or retry arbitrary errors.
        code = str(getattr(exc, 'code', '') or '')
        if code not in {'PGRST301', 'PGRST303', '401'}:
            raise
        reset_client()
        return query(client_factory()).execute().data or []
