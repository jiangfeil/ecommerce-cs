#!/usr/bin/env python3
"""把 docker/mysql/initdb/002_init_commerce.sql 的演示数据播种到当前数据库。

默认目标是项目内的 SQLite（commerce.db），因此**不需要安装 MySQL 就能跑通**。
如果你想用本地 MySQL，先把 .env 里的 DATABASE_URL 指到 MySQL，再执行本脚本。

用法：
    python seed_data.py            # 建表 + 播种（重复执行会清空重建）
    python seed_data.py --keep     # 只建表，不清空已有数据
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from app.config import settings
from app.database import engine
from app.models import Base
from sqlalchemy import text

BASE_DIR = Path(__file__).resolve().parent
SQL_FILE = BASE_DIR.parent / "docker" / "mysql" / "initdb" / "002_init_commerce.sql"

# 按依赖顺序清空（先子表后主表）
TABLES = [
    "logistics_traces",
    "logistics_records",
    "order_items",
    "refund_requests",
    "shipping_urge_requests",
    "orders",
    "products",
    "users",
]


def convert_json_object(sql: str) -> str:
    """把 MySQL 的 JSON_OBJECT('k','v',...) 转成 SQLite 能存的 JSON 字符串字面量。

    JSON_OBJECT('颜色', '远峰蓝', '容量', '256GB')
        ->  '{"颜色": "远峰蓝", "容量": "256GB"}'
    """
    pattern = re.compile(r"JSON_OBJECT\(([^()]*)\)", re.IGNORECASE)

    def _replace(match: re.Match[str]) -> str:
        inner = match.group(1)
        # 取出所有单引号字符串字面量，按顺序两两配对
        values = re.findall(r"'((?:[^']|'')*)'", inner)
        pairs = {
            values[i].replace("''", "'"): values[i + 1].replace("''", "'")
            for i in range(0, len(values) - 1, 2)
        }
        dumped = json.dumps(pairs, ensure_ascii=False)
        return "'" + dumped.replace("'", "''") + "'"

    return pattern.sub(_replace, sql)


def load_statements(sql_path: Path) -> list[str]:
    """抽取可执行的 INSERT 语句，跳过 MySQL 专有的 DDL / 权限语句。"""
    raw = sql_path.read_text(encoding="utf-8")
    raw = convert_json_object(raw)
    raw = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)
    raw = re.sub(r"^\s*--.*$", "", raw, flags=re.M)

    skip_prefixes = (
        "SET ",
        "CREATE DATABASE",
        "CREATE TABLE",
        "GRANT",
        "FLUSH",
        "USE ",
        "DROP ",
        "ALTER ",
    )
    statements: list[str] = []
    for chunk in raw.split(";"):
        stmt = chunk.strip()
        if not stmt:
            continue
        if stmt.upper().startswith(skip_prefixes):
            continue
        statements.append(stmt)
    return statements


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="保留已有数据，不清空")
    args = parser.parse_args()

    print(f"[1/3] 目标数据库: {settings.database_url}")
    Base.metadata.create_all(bind=engine)
    print("[2/3] 表结构已就绪")

    statements = load_statements(SQL_FILE)
    if not statements:
        print(f"!! 没有从 {SQL_FILE} 读到可执行语句", file=sys.stderr)
        return 1

    with engine.begin() as conn:
        if not args.keep:
            for table in TABLES:
                conn.execute(text(f"DELETE FROM {table}"))
            # 重置 SQLite 自增序列
            if settings.database_url.startswith("sqlite"):
                try:
                    conn.execute(text("DELETE FROM sqlite_sequence"))
                except Exception:
                    pass
        for stmt in statements:
            conn.execute(text(stmt))

    with engine.connect() as conn:
        print("[3/3] 播种完成，当前数据量：")
        for table in reversed(TABLES):
            count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
            print(f"      {table:24s} {count:>4d} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
