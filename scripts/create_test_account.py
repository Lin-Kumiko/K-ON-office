"""Create the shared trial account in an already initialised database.

    backend\\.venv\\Scripts\\python.exe scripts\\create_test_account.py [--username test]
Password: DOE_TEST_PASSWORD environment variable or hidden prompt. It must differ from the passwords of the
seed accounts, because the trial password is meant to be handed to other people.
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import select  # noqa: E402

from app.core.config import load_settings  # noqa: E402
from app.core.db import Database  # noqa: E402
from app.core.errors import ValidationFailed  # noqa: E402
from app.core.security import validate_password_strength, verify_password  # noqa: E402
from app.models import User  # noqa: E402
from app.seed import seed_test_account  # noqa: E402


def create(db: Database, password: str, iterations: int, username: str) -> int:
    validate_password_strength(password)
    with db.session(write=True) as s:
        for u in s.scalars(select(User).where(User.username != username)):
            if verify_password(password, u.password_hash):
                raise ValidationFailed(f"体验账号密码不能与已有账号（{u.username}）相同", code="PASSWORD_REUSED")
        uid = seed_test_account(s, password, iterations, username)
        s.commit()
    return uid or 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--username", default="test")
    args = ap.parse_args()
    password = os.environ.get("DOE_TEST_PASSWORD") or getpass.getpass("体验账号密码（与管理员等账号不同）：")
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        uid = create(db, password, settings.password_iterations, args.username)
    except ValidationFailed as e:
        print(f"[error] {e.message}")
        return 1
    finally:
        db.dispose()
    print(f"[ok] 体验账号 {args.username} 已创建" if uid else f"[skip] 账号 {args.username} 已存在")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
