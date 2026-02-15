"""SQLite DB 서비스 - 추출 데이터 저장 및 RAG 검색"""
import aiosqlite
import json
import logging
from pathlib import Path
from app.core.config import SQLITE_DB_PATH

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    file_type TEXT,
    file_name TEXT,
    status TEXT DEFAULT 'processing'
);

CREATE TABLE IF NOT EXISTS valves (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT REFERENCES sessions(id),
    tag TEXT,
    valve_type TEXT,
    valve_subtype TEXT,
    size TEXT,
    fluid TEXT,
    location TEXT,
    description TEXT,
    piping_class TEXT,
    schedule TEXT,
    sheet INTEGER,
    data_json TEXT
);

CREATE TABLE IF NOT EXISTS pipe_bom (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT REFERENCES sessions(id),
    page INTEGER,
    pipe_pieces TEXT,
    weld_count INTEGER,
    weld_items TEXT,
    dimensions_mm TEXT,
    has_loose BOOLEAN,
    data_json TEXT
);

CREATE TABLE IF NOT EXISTS dimensions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT REFERENCES sessions(id),
    view_name TEXT,
    overall_width_mm REAL,
    overall_height_mm REAL,
    data_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_valves_session ON valves(session_id);
CREATE INDEX IF NOT EXISTS idx_valves_tag ON valves(tag);
CREATE INDEX IF NOT EXISTS idx_valves_type ON valves(valve_type);
CREATE INDEX IF NOT EXISTS idx_bom_session ON pipe_bom(session_id);
"""


async def init_db():
    """DB 초기화"""
    async with aiosqlite.connect(str(SQLITE_DB_PATH)) as db:
        await db.executescript(SCHEMA_SQL)
        await db.commit()
    logger.info(f"DB initialized: {SQLITE_DB_PATH}")


async def create_session(session_id: str, file_type: str, file_name: str):
    async with aiosqlite.connect(str(SQLITE_DB_PATH)) as db:
        await db.execute(
            "INSERT INTO sessions (id, file_type, file_name) VALUES (?, ?, ?)",
            (session_id, file_type, file_name)
        )
        await db.commit()


async def update_session_status(session_id: str, status: str):
    async with aiosqlite.connect(str(SQLITE_DB_PATH)) as db:
        await db.execute("UPDATE sessions SET status = ? WHERE id = ?", (status, session_id))
        await db.commit()


async def save_valves(session_id: str, valves: list[dict]):
    async with aiosqlite.connect(str(SQLITE_DB_PATH)) as db:
        for v in valves:
            await db.execute(
                """INSERT INTO valves (session_id, tag, valve_type, valve_subtype,
                   size, fluid, location, description, piping_class, schedule, sheet, data_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, v["tag"], v.get("valve_type", ""), v.get("valve_subtype", ""),
                 v.get("size", ""), v.get("fluid", ""), v.get("location", ""),
                 v.get("description", ""), v.get("piping_class", ""), v.get("schedule", ""),
                 v.get("sheet", 0), json.dumps(v, ensure_ascii=False))
            )
        await db.commit()
    logger.info(f"Saved {len(valves)} valves for session {session_id}")


async def save_pipe_bom(session_id: str, pages_data: list[dict]):
    async with aiosqlite.connect(str(SQLITE_DB_PATH)) as db:
        for pd in pages_data:
            await db.execute(
                """INSERT INTO pipe_bom (session_id, page, pipe_pieces, weld_count,
                   weld_items, dimensions_mm, has_loose, data_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, pd["page"],
                 json.dumps(pd.get("pipe_pieces", [])),
                 pd.get("weld_count", 0),
                 json.dumps(pd.get("weld_items", [])),
                 json.dumps(pd.get("dimensions_mm", [])),
                 pd.get("has_loose", False),
                 json.dumps(pd, ensure_ascii=False))
            )
        await db.commit()
    logger.info(f"Saved {len(pages_data)} BOM pages for session {session_id}")


async def save_dimensions(session_id: str, dimensions: dict):
    async with aiosqlite.connect(str(SQLITE_DB_PATH)) as db:
        for view_name, view_data in dimensions.get("views", {}).items():
            await db.execute(
                """INSERT INTO dimensions (session_id, view_name, overall_width_mm,
                   overall_height_mm, data_json) VALUES (?, ?, ?, ?, ?)""",
                (session_id, view_name,
                 view_data.get("overall_width_mm", 0),
                 view_data.get("overall_height_mm", 0),
                 json.dumps(view_data, ensure_ascii=False))
            )
        await db.commit()


async def execute_query(sql: str, params: tuple = ()) -> list[dict]:
    """SQL 쿼리 실행 및 결과 반환 (AI 챗봇용)"""
    async with aiosqlite.connect(str(SQLITE_DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_session_info(session_id: str) -> dict | None:
    async with aiosqlite.connect(str(SQLITE_DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_db_schema() -> str:
    """DB 스키마 정보를 텍스트로 반환 (LLM 프롬프트용)"""
    async with aiosqlite.connect(str(SQLITE_DB_PATH)) as db:
        cursor = await db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL"
        )
        rows = await cursor.fetchall()
        return "\n\n".join(row[0] for row in rows)
