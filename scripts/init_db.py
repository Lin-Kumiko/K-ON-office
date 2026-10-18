"""Create / migrate the development database and insert base synthetic data.

Usage (from the project root):
    backend\\.venv\\Scripts\\python.exe scripts\\init_db.py
The initial password for all seed accounts is read from the DOE_SEED_PASSWORD environment
variable, or asked interactively (hidden input). It is never printed or stored in plain text.
"""
from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

from app.core.config import load_settings  # noqa: E402
from app.core.db import Database  # noqa: E402
from app.core.security import validate_password_strength  # noqa: E402
from app.core.errors import ValidationFailed  # noqa: E402
from app.models import Role  # noqa: E402
from app.seed import seed_base  # noqa: E402


def main() -> int:
    settings = load_settings()
    settings.ensure_dirs()
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.cmd_opts = type("o", (), {"x": [f"url={settings.database_url}"]})()
    command.upgrade(cfg, "head")
    print(f"[ok] 数据库已迁移到最新版本：{settings.database_url}")
    db = Database(settings.database_url)
    with db.session(write=True) as s:
        if s.query(Role).first() is not None:
            print("[skip] 已存在基础数据，未重复初始化")
            return 0
        password = os.environ.get("DOE_SEED_PASSWORD") or getpass.getpass("为所有种子账号设置初始密码（8 位以上，含字母和数字）：")
        try:
            validate_password_strength(password)
        except ValidationFailed as e:
            print(f"[error] {e.message}")
            return 1
        users = seed_base(s, password, settings.password_iterations)
        s.commit()
    print(f"[ok] 已写入基础合成数据：{len(users)} 个账号（{', '.join(users)}）")
    test_pw = os.environ.get("DOE_TEST_PASSWORD")
    if test_pw:
        from create_test_account import create
        try:
            create(db, test_pw, settings.password_iterations, "test")
            print("[ok] 已创建体验账号 test（体验访客角色，无管理权限）")
        except ValidationFailed as e:
            print(f"[warn] 体验账号未创建：{e.message}")
    else:
        print("[info] 未设置 DOE_TEST_PASSWORD，跳过体验账号；之后可运行 scripts\\create_test_account.py")
    db.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
