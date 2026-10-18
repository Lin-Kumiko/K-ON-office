"""Reset the password of local accounts in the development database (hidden input, nothing printed).

    backend\\.venv\\Scripts\\python.exe scripts\\reset_password.py saito      # one account
    backend\\.venv\\Scripts\\python.exe scripts\\reset_password.py --all      # every account
The new password can also come from the DOE_NEW_PASSWORD environment variable.
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
from app.core.security import hash_password, validate_password_strength  # noqa: E402
from app.models import User  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("username", nargs="?")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    if not args.all and not args.username:
        ap.error("请指定用户名或 --all")
    password = os.environ.get("DOE_NEW_PASSWORD") or getpass.getpass("新密码（8 位以上，含字母和数字）：")
    try:
        validate_password_strength(password)
    except ValidationFailed as e:
        print(f"[error] {e.message}")
        return 1
    settings = load_settings()
    db = Database(settings.database_url)
    with db.session(write=True) as s:
        stmt = select(User) if args.all else select(User).where(User.username == args.username)
        users = list(s.scalars(stmt))
        if not users:
            print("[error] 未找到账号")
            return 1
        h = hash_password(password, settings.password_iterations)
        for u in users:
            u.password_hash, u.failed_attempts, u.locked_until, u.must_change_password = h, 0, None, False
        s.commit()
    db.dispose()
    print(f"[ok] 已重置 {len(users)} 个账号的密码")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
