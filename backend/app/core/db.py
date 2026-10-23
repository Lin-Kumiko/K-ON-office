"""SQLite engine and session factories.

Concurrency model (see ARCHITECTURE.md):
* WAL journal, foreign keys on, busy_timeout so writers queue instead of failing.
* Read sessions open a deferred ``BEGIN``; write sessions open ``BEGIN IMMEDIATE`` so the
  RESERVED lock is taken before any read inside the transaction. This serialises
  read-modify-write sequences across processes/threads and prevents lost updates
  without relying on row locks that SQLite does not have.
"""
from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def make_engine(url: str) -> Engine:
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False, "timeout": 30},
        pool_size=10,
        max_overflow=20,
    )

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):  # pragma: no cover - exercised implicitly
        dbapi_conn.isolation_level = None  # we emit BEGIN ourselves
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA cache_size=-16000")  # 16 MB page cache per connection (default is 2 MB)
        cur.execute("PRAGMA temp_store=MEMORY")  # sorts / temp b-trees for ORDER BY and GROUP BY stay in RAM
        cur.close()

    @event.listens_for(engine, "begin")
    def _on_begin(conn):
        mode = conn.get_execution_options().get("sqlite_begin", "DEFERRED")
        conn.exec_driver_sql("BEGIN IMMEDIATE" if mode == "IMMEDIATE" else "BEGIN")

    return engine


class Database:
    def __init__(self, url: str):
        self.url = url
        self.engine = make_engine(url)
        write_engine = self.engine.execution_options(sqlite_begin="IMMEDIATE")
        self.read_session = sessionmaker(bind=self.engine, expire_on_commit=False, autoflush=True)
        self.write_session = sessionmaker(bind=write_engine, expire_on_commit=False, autoflush=True)

    def session(self, write: bool = False) -> Session:
        return (self.write_session if write else self.read_session)()

    def dispose(self) -> None:
        try:
            with self.engine.connect() as conn:
                # lets SQLite refresh statistics for tables whose size changed a lot (cheap, recommended on close)
                conn.exec_driver_sql("PRAGMA optimize")
        except Exception:  # pragma: no cover - best effort on shutdown
            pass
        self.engine.dispose()
