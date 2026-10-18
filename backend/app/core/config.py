"""Runtime settings, read from environment variables (prefix DOE_)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    env: str = "development"
    data_dir: Path = PROJECT_DIR / "data"
    database_url: str = ""
    timezone: str = "Asia/Shanghai"
    session_hours: int = 12
    password_iterations: int = 210_000
    max_login_failures: int = 5
    lockout_minutes: int = 15
    max_upload_bytes: int = 10 * 1024 * 1024
    # Simulated punches (custom punch_time) are allowed for everyone when True;
    # otherwise only users holding attendance:manage may simulate.
    simulation_mode: bool = True
    # Self-service registration (username + password) and its per-IP hourly limit.
    allow_registration: bool = True
    register_limit_per_hour: int = 5
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"])
    frontend_dist: Path = PROJECT_DIR / "frontend" / "dist"
    # Frozen business clock, honoured only when env == "test" (reproducible tests).
    fixed_now: str | None = None

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)


def load_settings(**overrides) -> Settings:
    data_dir = Path(os.environ.get("DOE_DATA_DIR", str(PROJECT_DIR / "data")))
    s = Settings(
        env=os.environ.get("DOE_ENV", "development"),
        data_dir=data_dir,
        database_url=os.environ.get("DOE_DATABASE_URL", ""),
        timezone=os.environ.get("DOE_TIMEZONE", "Asia/Shanghai"),
        session_hours=int(os.environ.get("DOE_SESSION_HOURS", "12")),
        password_iterations=int(os.environ.get("DOE_PASSWORD_ITERATIONS", "210000")),
        simulation_mode=_bool("DOE_SIMULATION_MODE", True),
        allow_registration=_bool("DOE_ALLOW_REGISTRATION", True),
        register_limit_per_hour=int(os.environ.get("DOE_REGISTER_LIMIT_PER_HOUR", "5")),
        fixed_now=os.environ.get("DOE_FIXED_NOW") or None,
    )
    for key, value in overrides.items():
        setattr(s, key, value)
    if not s.database_url:
        s.database_url = f"sqlite:///{(s.data_dir / 'dev.sqlite3').as_posix()}"
    return s
