"""Start the system locally on Windows.

    backend\\.venv\\Scripts\\python.exe scripts\\start.py          # dev: API :8000 + Vite :5173
    backend\\.venv\\Scripts\\python.exe scripts\\start.py --prod   # build frontend, API serves it on :8000
    backend\\.venv\\Scripts\\python.exe scripts\\start.py --prod --host 0.0.0.0   # also reachable from the LAN
"""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
PY = BACKEND / ".venv" / "Scripts" / "python.exe"


def lan_ip() -> str:
    """Best-effort LAN address of this machine (no packet is actually sent)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sk:
        try:
            sk.connect(("192.168.0.1", 80))
            return sk.getsockname()[0]
        except OSError:
            return "本机IP"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prod", action="store_true", help="构建前端并由后端在 8000 端口统一提供")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1", help="监听地址；0.0.0.0 表示允许局域网内其他电脑访问")
    args = ap.parse_args()
    if not PY.exists():
        print("[error] 未找到 backend/.venv，请先按 README 创建虚拟环境并安装依赖")
        return 1
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if args.prod:
        subprocess.run([npm, "run", "build"], cwd=FRONTEND, check=True, shell=False)
    api = subprocess.Popen([str(PY), "-m", "uvicorn", "app.main:create_app", "--factory", "--host", args.host,
                            "--port", str(args.port)], cwd=BACKEND, env=os.environ.copy())
    procs = [api]
    if not args.prod:
        dev = [npm, "run", "dev"] + (["--", "--host", args.host] if args.host != "127.0.0.1" else [])
        procs.append(subprocess.Popen(dev, cwd=FRONTEND, shell=False))
        print("前端：http://localhost:5173   API 文档：http://127.0.0.1:%d/docs" % args.port)
    else:
        print("系统：http://127.0.0.1:%d   API 文档：http://127.0.0.1:%d/docs" % (args.port, args.port))
    if args.host == "0.0.0.0":
        port = args.port if args.prod else 5173
        print("局域网访问：http://%s:%d （如无法访问，请在 Windows 防火墙中自行放行该端口）" % (lan_ip(), port))
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
