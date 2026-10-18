"""Start the system locally on Windows.

    backend\\.venv\\Scripts\\python.exe scripts\\start.py          # dev: API :8000 + Vite :5173
    backend\\.venv\\Scripts\\python.exe scripts\\start.py --prod   # build frontend, API serves it on :8000
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
PY = BACKEND / ".venv" / "Scripts" / "python.exe"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prod", action="store_true", help="构建前端并由后端在 8000 端口统一提供")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    if not PY.exists():
        print("[error] 未找到 backend/.venv，请先按 README 创建虚拟环境并安装依赖")
        return 1
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if args.prod:
        subprocess.run([npm, "run", "build"], cwd=FRONTEND, check=True, shell=False)
    api = subprocess.Popen([str(PY), "-m", "uvicorn", "app.main:create_app", "--factory", "--host", "127.0.0.1",
                            "--port", str(args.port)], cwd=BACKEND, env=os.environ.copy())
    procs = [api]
    if not args.prod:
        procs.append(subprocess.Popen([npm, "run", "dev"], cwd=FRONTEND, shell=False))
        print("前端：http://localhost:5173   API 文档：http://127.0.0.1:%d/docs" % args.port)
    else:
        print("系统：http://127.0.0.1:%d   API 文档：http://127.0.0.1:%d/docs" % (args.port, args.port))
    try:
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
