import sqlite3
from pathlib import Path

DB_PATH = Path("data/orthoflow.db")

AGENTI = [
    "Pasquale",
    "Maurizio",
    "Mariano Borrelli",
    "Mariano Gargiulo",
    "Susi",
    "Giampiero",
    "Francesco De Lisi",
    "Francesco Cirillo",
    "Cristiano",
]

def get_conn():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def add_column_if_missing(cur, table, column, definition):
    cols = [r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS utenti(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            ruolo TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS clienti(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codice_cliente TEXT UNIQUE,
            descrizione TEXT,
            citta TEXT,
            provincia TEXT,
            piva TEXT,
            stato_record TEXT DEFAULT 'Attivo'
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS agenti(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT UNIQUE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS magazzino(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codice TEXT,
            descrizione TEXT,
            lotto TEXT,
            scadenza TEXT,
            quantita REAL,
            ubicazione TEXT,
            origine TEXT DEFAULT 'CONTO DEPOSITO',
            stato_record TEXT DEFAULT 'Attivo',
            UNIQUE(codice, lotto, origine)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS offerte_header(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_offerta TEXT,
            linea TEXT,
            data_inizio TEXT,
            data_fine TEXT,
            note TEXT,
            stato_record TEXT DEFAULT 'Attivo'
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS offerte_clienti(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            offerta_id INTEGER,
            codice_cliente TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS offerte_prezzi(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            offerta_id INTEGER,
            codice TEXT,
            descrizione TEXT,
            prezzo REAL,
            iva TEXT,
            cnd TEXT,
            rdm TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS interventi(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_intervento TEXT,
            codice_cliente TEXT,
            cliente TEXT,
            cartella_clinica TEXT,
            agente TEXT,
            chirurgo TEXT,
            linea TEXT,
            allegato TEXT,
            note TEXT,
            stato_record TEXT DEFAULT 'Attivo',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS righe_intervento(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            intervento_id INTEGER,
            codice TEXT,
            descrizione TEXT,
            lotto TEXT,
            scadenza TEXT,
            quantita REAL,
            produttore TEXT,
            validazione TEXT,
            origine TEXT,
            prezzo REAL,
            totale REAL,
            reintegro INTEGER DEFAULT 1,
            stato_record TEXT DEFAULT 'Attivo'
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ddt(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero_ddt TEXT,
            data_ddt TEXT,
            tipo_ddt TEXT,
            cliente TEXT,
            allegato TEXT,
            note TEXT,
            stato_record TEXT DEFAULT 'Attivo'
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ddt_righe(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ddt_id INTEGER,
            codice TEXT,
            descrizione TEXT,
            lotto TEXT,
            scadenza TEXT,
            quantita REAL,
            origine TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS order_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero_ordine TEXT,
            riferimento_po TEXT,
            data_ordine TEXT,
            cliente TEXT,
            stato TEXT,
            totale REAL,
            stato_record TEXT DEFAULT 'Attivo'
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS order_details(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero_ordine TEXT,
            codice TEXT,
            descrizione TEXT,
            quantita REAL,
            prezzo REAL,
            totale REAL,
            stato_record TEXT DEFAULT 'Attivo'
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS chiusure(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mese TEXT,
            numero_ordine TEXT,
            codice TEXT,
            descrizione TEXT,
            quantita REAL,
            valore REAL,
            stato_record TEXT DEFAULT 'Attivo'
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS alias_strutture(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alias TEXT UNIQUE NOT NULL,
            codice_cliente TEXT NOT NULL,
            descrizione_cliente TEXT,
            priorita INTEGER DEFAULT 100,
            note TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS anomalie(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT,
            gravita TEXT,
            descrizione TEXT,
            stato TEXT DEFAULT 'Aperta',
            stato_record TEXT DEFAULT 'Attivo',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            utente TEXT,
            azione TEXT,
            tabella TEXT,
            riferimento TEXT,
            dettagli TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    for table in [
        "clienti",
        "magazzino",
        "offerte_header",
        "interventi",
        "righe_intervento",
        "ddt",
        "order_history",
        "order_details",
        "chiusure",
        "anomalie",
    ]:
        add_column_if_missing(cur, table, "stato_record", "TEXT DEFAULT 'Attivo'")

    cur.execute(
        "INSERT OR IGNORE INTO utenti(username,password,ruolo) VALUES('admin','admin','Admin')"
    )
    cur.execute(
        "INSERT OR IGNORE INTO utenti(username,password,ruolo) VALUES('collaboratore','1234','Collaboratore')"
    )

    for agente in AGENTI:
        cur.execute("INSERT OR IGNORE INTO agenti(nome) VALUES(?)", (agente,))

    conn.commit()
    conn.close()
