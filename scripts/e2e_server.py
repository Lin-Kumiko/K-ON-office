"""Start an isolated backend for browser E2E tests.

Creates a fresh SQLite database under tests/.e2e-data (migrations + base seed with the password
from E2E_PASSWORD), then serves the API and the built frontend (frontend/dist) on --port.
Never touches data/dev.sqlite3.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
DATA = ROOT / "tests" / ".e2e-data"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    password = os.environ.get("E2E_PASSWORD")
    if not password:
        print("E2E_PASSWORD is required", file=sys.stderr)
        return 2
    if DATA.exists():
        shutil.rmtree(DATA)  # only our own dedicated E2E directory
    DATA.mkdir(parents=True)
    db_path = DATA / "e2e.sqlite3"
    os.environ["DOE_DATA_DIR"] = str(DATA)
    os.environ["DOE_DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ.setdefault("DOE_ENV", "e2e")
    os.environ.setdefault("DOE_PASSWORD_ITERATIONS", "20000")

    from alembic import command
    from alembic.config import Config

    from app.core.config import load_settings
    from app.core.db import Database
    from app.seed import seed_base

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.cmd_opts = type("o", (), {"x": [f"url=sqlite:///{db_path.as_posix()}"]})()
    command.upgrade(cfg, "head")
    settings = load_settings()
    db = Database(settings.database_url)
    with db.session(write=True) as s:
        seed_base(s, password, settings.password_iterations)
        s.commit()
    db.dispose()

    import uvicorn
    from app.main import create_app
    uvicorn.run(create_app(load_settings()), host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
