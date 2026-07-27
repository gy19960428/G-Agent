import sqlite3
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from flask import current_app, g


def is_postgres_url(database_url):
    return database_url.startswith(('postgresql://', 'postgres://'))


def resolve_sqlite_path(database_url):
    if database_url.startswith('sqlite:///'):
        raw_path = database_url.removeprefix('sqlite:///')
    else:
        raw_path = database_url
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path(current_app.instance_path) / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def sql_for_driver(sql):
    database_url = current_app.config['DATABASE_URL']
    if is_postgres_url(database_url):
        return sql.replace('?', '%s')
    return sql


def get_db():
    if 'db' not in g:
        database_url = current_app.config['DATABASE_URL']
        if is_postgres_url(database_url):
            g.db = psycopg.connect(database_url, row_factory=dict_row)
        elif database_url.startswith('sqlite'):
            db_path = resolve_sqlite_path(database_url)
            g.db = sqlite3.connect(db_path)
            g.db.row_factory = sqlite3.Row
            g.db.execute('PRAGMA foreign_keys = ON')
        else:
            raise RuntimeError(f'不支持的数据库地址: {database_url}')
    return g.db


def close_db(_error=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    database_url = current_app.config['DATABASE_URL']
    schema_name = 'schema.postgres.sql' if is_postgres_url(database_url) else 'schema.sql'
    schema_path = Path(__file__).with_name(schema_name)
    schema_sql = schema_path.read_text(encoding='utf-8')
    if is_postgres_url(database_url):
        for statement in schema_sql.split(';'):
            if statement.strip():
                db.execute(statement)
    else:
        db.executescript(schema_sql)
    db.commit()


def query_one(sql, args=()):
    return get_db().execute(sql_for_driver(sql), args).fetchone()


def query_all(sql, args=()):
    return get_db().execute(sql_for_driver(sql), args).fetchall()


def execute(sql, args=()):
    return get_db().execute(sql_for_driver(sql), args)
