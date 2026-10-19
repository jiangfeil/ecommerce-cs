#!/usr/bin/env python3
"""把项目从 SQLite 切到本地 MySQL。

用法：
    python switch_to_mysql.py --password 你的密码
    python switch_to_mysql.py --password 你的密码 --user root --host 127.0.0.1 --port 3306

它会做四件事：
  1. 测试连接（失败立刻报错，不会留下半截状态）
  2. 创建 commerce / customer_service 两个库
  3. 把 db/commerce.sql 的表结构和演示数据灌进 commerce
  4. 改写两个后端目录下的 .env，把 DATABASE_URL 指向 MySQL

customer_service 库只建库不建表——那张表由客服后端的 SQLAlchemy 模型自动创建，
以模型为准，避免 SQL 与代码字段不一致。

想切回 SQLite：删掉 .env 里的 MySQL 那行，取消 SQLite 那行注释即可。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import quote_plus

try:
    import pymysql
except ImportError:
    print("缺少 pymysql，请先执行： .venv\\Scripts\\pip install pymysql")
    raise SystemExit(1) from None

ROOT = Path(__file__).resolve().parent
COMMERCE_SQL = ROOT / "db" / "commerce.sql"
ECOMMERCE_ENV = ROOT / "ecommerce-service-backend" / ".env"
CUSTOMER_ENV = ROOT / "customer-service-backend" / ".env"

SKIP_PREFIXES = ("GRANT", "FLUSH")


def split_statements(sql: str) -> list[str]:
    """按分号切分，跳过注释与权限语句。"""
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.S)
    sql = re.sub(r"^\s*--.*$", "", sql, flags=re.M)
    statements: list[str] = []
    for chunk in sql.split(";"):
        stmt = chunk.strip()
        if not stmt:
            continue
        if stmt.upper().startswith(SKIP_PREFIXES):
            continue
        statements.append(stmt)
    return statements


def seed_commerce(conn) -> int:
    statements = split_statements(COMMERCE_SQL.read_text(encoding="utf-8"))
    executed = 0
    with conn.cursor() as cursor:
        for stmt in statements:
            cursor.execute(stmt)
            executed += 1
        conn.commit()
    return executed


def rewrite_env(path: Path, mysql_url: str, sqlite_pattern: str) -> str:
    """把 .env 里的 DATABASE_URL 改成 MySQL，同时保留 SQLite 那行作注释。"""
    if not path.exists():
        return f"跳过（文件不存在）: {path}"

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    output: list[str] = []
    replaced = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("DATABASE_URL=sqlite"):
            if not replaced:
                output.append(f"DATABASE_URL={mysql_url}")
                output.append(f"# {sqlite_pattern}")
                replaced = True
            continue
        if stripped.startswith("DATABASE_URL=mysql"):
            if not replaced:
                output.append(f"DATABASE_URL={mysql_url}")
                replaced = True
            continue
        if stripped.startswith("# DATABASE_URL=sqlite"):
            output.append(f"# {sqlite_pattern}")
            continue
        if stripped.startswith("# DATABASE_URL=mysql"):
            continue
        output.append(line)

    if not replaced:
        output.insert(0, f"DATABASE_URL={mysql_url}")
    path.write_text("\n".join(output) + "\n", encoding="utf-8")
    return "已更新"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3306)
    parser.add_argument("--user", default="root")
    parser.add_argument("--password", required=True)
    parser.add_argument(
        "--skip-seed",
        action="store_true",
        help="只建库和改配置，不灌入演示数据",
    )
    args = parser.parse_args()

    print(f"[1/4] 连接 MySQL {args.user}@{args.host}:{args.port} ...")
    try:
        conn = pymysql.connect(
            host=args.host,
            port=args.port,
            user=args.user,
            password=args.password,
            charset="utf8mb4",
            autocommit=True,
        )
    except pymysql.err.OperationalError as exc:
        code = exc.args[0] if exc.args else ""
        print(f"  连接失败: {exc.args[-1]}")
        if code == 1045:
            print("  账号或密码不正确。可以先在命令行确认：")
            print(f'    mysql -u{args.user} -p -h {args.host} -P {args.port} -e "select 1"')
        raise SystemExit(1) from None

    print("  连接成功")

    print("[2/4] 创建数据库 ...")
    with conn.cursor() as cursor:
        cursor.execute(
            "CREATE DATABASE IF NOT EXISTS `commerce` "
            "DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_unicode_ci"
        )
        cursor.execute(
            "CREATE DATABASE IF NOT EXISTS `customer_service` "
            "DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_unicode_ci"
        )
    print("  commerce / customer_service 就绪")

    if args.skip_seed:
        print("[3/4] 跳过演示数据")
    else:
        print("[3/4] 灌入演示数据（会重建 commerce 中的表）...")
        with conn.cursor() as cursor:
            cursor.execute("USE `commerce`")
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
            for table in (
                "logistics_traces",
                "logistics_records",
                "order_items",
                "refund_requests",
                "shipping_urge_requests",
                "orders",
                "products",
                "users",
            ):
                # MySQL 不支持 TRUNCATE ... IF EXISTS，先 DROP 再让 002 重建
                cursor.execute(f"DROP TABLE IF EXISTS `{table}`")
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
        count = seed_commerce(conn)
        print(f"  执行 {count} 条 SQL 语句")

        with conn.cursor() as cursor:
            for table in ("users", "products", "orders"):
                cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
                print(f"  {table}: {cursor.fetchone()[0]} 行")

    print("[4/4] 更新 .env ...")
    encoded = quote_plus(args.password)
    commerce_url = (
        f"mysql+pymysql://{args.user}:{encoded}@{args.host}:{args.port}"
        f"/commerce?charset=utf8mb4"
    )
    customer_url = (
        f"mysql+aiomysql://{args.user}:{encoded}@{args.host}:{args.port}"
        f"/customer_service?charset=utf8mb4"
    )
    print("  中台  :", rewrite_env(ECOMMERCE_ENV, commerce_url, "DATABASE_URL=sqlite:///commerce.db"))
    print("  客服  :", rewrite_env(CUSTOMER_ENV, customer_url, "DATABASE_URL=sqlite+aiosqlite:///./customer_service.db"))

    conn.close()
    print("\n完成。接下来：")
    print("  1. 重启两个后端服务（.env 只在启动时读取）")
    print("  2. 客服后端的 dialogue_states 表会在启动时自动创建")
    print("  3. 验证： curl http://127.0.0.1:18082/health")
    return 0


if __name__ == "__main__":
    sys.exit(main())
