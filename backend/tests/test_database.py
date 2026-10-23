"""Database layer: migrations, foreign keys, unique / check constraints, transactions and rollback."""
import sqlite3

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.config import BACKEND_DIR
from app.models import Base
from tests.conftest import migrate


def _cfg(path):
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.cmd_opts = type("o", (), {"x": [f"url=sqlite:///{path.as_posix()}"]})()
    return cfg


def test_migration_upgrade_downgrade_and_no_drift(tmp_path):
    db = tmp_path / "m.sqlite3"
    migrate(db)
    con = sqlite3.connect(db)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert set(Base.metadata.tables) <= tables
    triggers = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    assert {"trg_meeting_no_overlap_insert", "trg_meeting_no_overlap_update"} <= triggers
    con.close()
    command.check(_cfg(db))  # models and migrations are in sync (raises on drift)
    command.downgrade(_cfg(db), "base")
    con = sqlite3.connect(db)
    assert {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")} == {"alembic_version"}
    con.close()
    command.upgrade(_cfg(db), "head")


def _exec(app, sql, *params):
    with app.state.db.engine.begin() as conn:
        return conn.exec_driver_sql(sql, params)


def test_foreign_keys_enforced(app):
    with pytest.raises(IntegrityError):
        _exec(app, "INSERT INTO employees (employee_no, name, department_id, hire_date, status, version, created_at, "
                   "updated_at) VALUES ('X1','x',99999,'2026-01-01','regular',1,'2026-01-01','2026-01-01')")
    with pytest.raises(IntegrityError):  # RESTRICT: department with employees cannot be deleted
        _exec(app, "DELETE FROM departments WHERE code='MUSIC'")


def test_unique_constraints(app):
    with pytest.raises(IntegrityError):
        _exec(app, "UPDATE employees SET employee_no='HTT0001' WHERE employee_no='HTT0002'")
    with pytest.raises(IntegrityError):
        _exec(app, "UPDATE users SET username='yui' WHERE username='mio'")
    with pytest.raises(IntegrityError):
        _exec(app, "INSERT INTO leave_balances (employee_id, leave_type_id, year, total_hours, used_hours, "
                   "pending_hours, created_at, updated_at) SELECT employee_id, leave_type_id, year, 0,0,0, created_at, "
                   "updated_at FROM leave_balances LIMIT 1")


def test_check_constraints(app):
    with pytest.raises(IntegrityError):  # balance overdraw
        _exec(app, "UPDATE leave_balances SET used_hours = total_hours + 1 WHERE id = (SELECT min(id) FROM leave_balances)")
    with pytest.raises(IntegrityError):
        _exec(app, "UPDATE employees SET status='fired' WHERE employee_no='HTT0001'")
    with pytest.raises(IntegrityError):
        _exec(app, "UPDATE employees SET manager_id=id WHERE employee_no='HTT0002'")
    with pytest.raises(IntegrityError):
        _exec(app, "INSERT INTO expense_items (claim_id, category_id, occurred_on, amount_cents, created_at) "
                   "VALUES (1, 1, '2026-01-01', -5, '2026-01-01')")


def test_partial_unique_running_instance(app):
    _exec(app, "INSERT INTO wf_instances (definition_id, version_id, business_type, business_id, title, initiator_id,"
               " status, variables, started_at, version_row) VALUES (1,1,'leave',777,'t',1,'running','{}','2026-01-01',1)")
    with pytest.raises(IntegrityError):
        _exec(app, "INSERT INTO wf_instances (definition_id, version_id, business_type, business_id, title, "
                   "initiator_id, status, variables, started_at, version_row) VALUES "
                   "(1,1,'leave',777,'t',1,'running','{}','2026-01-01',1)")
    # a finished one may coexist
    _exec(app, "INSERT INTO wf_instances (definition_id, version_id, business_type, business_id, title, initiator_id,"
               " status, variables, started_at, version_row) VALUES (1,1,'leave',777,'t',1,'rejected','{}','2026-01-01',1)")


def test_transaction_rollback_leaves_no_partial_state(app):
    db = app.state.db
    with db.session(write=True) as s:
        before = s.execute(text("SELECT count(*) FROM departments")).scalar()
        s.execute(text("INSERT INTO departments (name, code, sort, status, created_at, updated_at) "
                       "VALUES ('临时', 'TMP', 0, 'active', '2026-01-01', '2026-01-01')"))
        with pytest.raises(IntegrityError):
            s.execute(text("INSERT INTO departments (name, code, sort, status, created_at, updated_at) "
                           "VALUES ('临时2', 'TMP', 0, 'active', '2026-01-01', '2026-01-01')"))
        s.rollback()
    with db.session() as s:
        assert s.execute(text("SELECT count(*) FROM departments")).scalar() == before


def test_sqlite_pragmas(app):
    with app.state.db.engine.connect() as c:
        assert c.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert c.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert c.exec_driver_sql("PRAGMA busy_timeout").scalar() == 30000
        assert c.exec_driver_sql("PRAGMA cache_size").scalar() == -16000
        assert c.exec_driver_sql("PRAGMA temp_store").scalar() == 2  # MEMORY
