import json
import os
import sqlite3
from contextlib import contextmanager


@contextmanager
def transaction():
    connection = sqlite3.connect(os.getenv('DATABASE_PATH', 'clinichelper.db'), timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('BEGIN IMMEDIATE')
        connection.execute('CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        connection.execute('CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, case_id TEXT, actor TEXT, event TEXT, detail TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)')
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get(connection, case_id):
    row = connection.execute('SELECT payload FROM cases WHERE id=?', (case_id,)).fetchone()
    return json.loads(row['payload']) if row else None


def save(connection, case):
    connection.execute('INSERT INTO cases VALUES (?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',
                       (case['id'], json.dumps(case)))


def audit(connection, case_id, actor, event, detail):
    connection.execute('INSERT INTO audit(case_id,actor,event,detail) VALUES(?,?,?,?)',
                       (case_id, actor, event, json.dumps(detail)))
