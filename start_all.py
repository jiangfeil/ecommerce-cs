#!/usr/bin/env python3
"""一键启动电商小二的全部服务。

    python start_all.py            # 启动三个服务并打开浏览器
    python start_all.py --no-open  # 只启动，不打开浏览器

按 Ctrl+C 可同时停止全部服务。
"""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IS_WINDOWS = os.name == "nt"


def venv_python() -> Path:
    """项目根目录下统一的一个虚拟环境，两个后端共用。"""
    candidate = ROOT / (".venv/Scripts/python.exe" if IS_WINDOWS else ".venv/bin/python")
    if candidate.exists():
        return candidate
    print("  [提示] 未找到 .venv，改用当前解释器。首次使用请先执行：")
    print("         uv venv .venv && uv pip install -r requirements.txt")
    return Path(sys.executable)


def port_in_use(port: int) -> bool:
    """端口上已经有服务在监听（通常是上一次没关干净）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def wait_port(port: int, timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.4)
    return False


def database_url(project_dir: Path) -> str:
    """读取 .env 里的 DATABASE_URL，用来判断当前连的是 SQLite 还是 MySQL。"""
    env_file = project_dir / ".env"
    if not env_file.exists():
        return ""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("DATABASE_URL="):
            return stripped.split("=", 1)[1]
    return ""


def _node_search_dirs() -> list[Path]:
    """Node.js 的常见安装位置（PATH 里找不到时再翻这些）。"""
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local_appdata = os.environ.get("LOCALAPPDATA", "")

    dirs = [Path(program_files) / "nodejs", Path(program_files_x86) / "nodejs"]
    if local_appdata:
        dirs.append(Path(local_appdata) / "Programs" / "nodejs")
    return [d for d in dirs if d.exists()]


def npm_command() -> list[str] | None:
    """定位 npm，返回命令前缀，找不到返回 None。

    查找顺序：环境变量 NPM_CMD → PATH → 常见安装目录 → 用 node 直接跑 npm 入口脚本。
    返回列表是因为有两种启动方式：直接调 npm.cmd，或者 node + npm-cli.js。
    """
    override = os.environ.get("NPM_CMD")
    if override and Path(override).exists():
        return [override]

    for name in ("npm.cmd", "npm.exe", "npm.bat"):
        found = shutil.which(name)
        if found:
            return [found]

    for base in _node_search_dirs():
        for name in ("npm.cmd", "npm.exe"):
            candidate = base / name
            if candidate.exists():
                return [str(candidate)]

    node = shutil.which("node") or shutil.which("node.exe")
    if node:
        cli = Path(node).parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
        if cli.exists():
            return [node, str(cli)]
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()

    processes: list[tuple[str, subprocess.Popen]] = []

    def spawn(name: str, cwd: Path, cmd: list[str], port: int | None = None) -> None:
        if port is not None and port_in_use(port):
            print(f"  [跳过] {name} —— 端口 {port} 已被占用，可能上次没关干净")
            return
        print(f"  启动 {name} ...")
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0
        try:
            process = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )
        except OSError as exc:
            print(f"  [失败] {name} 启动不了：{exc}")
            return
        processes.append((name, process))

    print("=" * 64)
    print("电商小二 · 启动中")
    print("=" * 64)

    python = venv_python()

    # 1. 模拟电商中台
    ecommerce_dir = ROOT / "ecommerce-service-backend"
    db_url = database_url(ecommerce_dir)
    if db_url.startswith("sqlite"):
        if not (ecommerce_dir / "commerce.db").exists():
            print("  首次运行，初始化中台演示数据 ...")
            subprocess.run(
                [str(python), "seed_data.py"],
                cwd=str(ecommerce_dir),
                check=False,
            )
    elif db_url.startswith("mysql"):
        print("  中台使用 MySQL，跳过 SQLite 播种")
    else:
        print("  未检测到 DATABASE_URL，将使用 SQLite 默认值")
    spawn(
        "电商中台 :18081",
        ecommerce_dir,
        [str(python), "-m", "uvicorn", "app.app:app", "--host", "127.0.0.1", "--port", "18081"],
        port=18081,
    )

    # 2. 智能客服后端
    customer_dir = ROOT / "customer-service-backend"
    spawn(
        "客服后端 :18082",
        customer_dir,
        [str(python), "-m", "uvicorn", "app.app:app", "--host", "127.0.0.1", "--port", "18082"],
        port=18082,
    )

    # 3. 前端
    frontend_dir = ROOT / "customer-service-frontend"
    npm = npm_command()
    if npm is None:
        print("  [跳过] 没找到 npm，前端不会启动（两个后端不受影响）。")
        print("         解决方式二选一：")
        print("         1) 安装 Node.js（https://nodejs.org 下载 LTS 版），装完重开 PyCharm")
        print("         2) 设置环境变量 NPM_CMD，指向本机的 npm.cmd")
        print("         临时办法：cd customer-service-frontend && npm run dev")
    else:
        if not (frontend_dir / "node_modules").exists():
            print("  首次运行，安装前端依赖（约 1 分钟）...")
            subprocess.run([*npm, "install"], cwd=str(frontend_dir), check=False)
        spawn("前端 :5173", frontend_dir, [*npm, "run", "dev"], port=5173)

    print("\n  等待服务就绪 ...")
    ready = {
        "电商中台": wait_port(18081, 60),
        "客服后端": wait_port(18082, 60),
        "前端": wait_port(5173, 90),
    }
    for name, ok in ready.items():
        print(f"  {'[OK]  ' if ok else '[FAIL]'} {name}")

    if not ready.get("前端"):
        print("\n  [提示] 前端没起来，页面会报「拒绝连接」。常见原因是没装 Node.js：")
        print("         装好后重跑本脚本即可；也可以手动起前端：")
        print("         cd customer-service-frontend")
        print("         npm run dev")

    print("\n" + "=" * 64)
    print("  聊天界面: http://127.0.0.1:5173")
    print("  客服文档: http://127.0.0.1:18082/docs")
    print("  中台文档: http://127.0.0.1:18081/docs")
    print("=" * 64)
    print("  按 Ctrl+C 停止全部服务\n")

    if not args.no_open and ready.get("前端"):
        try:
            webbrowser.open("http://127.0.0.1:5173")
        except Exception:  # noqa: BLE001
            pass

    try:
        while True:
            for name, process in list(processes):
                if process.poll() is not None:
                    print(f"  [退出] {name} 已停止（退出码 {process.returncode}）")
                    processes.remove((name, process))
            if not processes:
                print("所有服务已停止。")
                return 0
            time.sleep(2)
    except KeyboardInterrupt:
        print("\n正在停止服务 ...")
        for _, process in processes:
            try:
                process.terminate()
            except Exception:  # noqa: BLE001
                pass
        time.sleep(1)
        for _, process in processes:
            if process.poll() is None:
                try:
                    process.kill()
                except Exception:  # noqa: BLE001
                    pass
        print("已停止。")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
