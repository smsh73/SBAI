"""P&ID Symbol Library API 라우터"""
import json
import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from app.core.config import OUTPUT_DIR
from app.services.db_service import get_session_info, execute_query

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/symbols/{session_id}")
async def get_symbol_library(
    session_id: str,
    category: str | None = Query(None, description="Filter by category"),
    search: str | None = Query(None, description="Search description/name"),
):
    """세션의 전체 심볼 라이브러리 조회 (카테고리/검색 필터 지원)"""
    session = await get_session_info(session_id)
    if not session:
        raise HTTPException(404, "세션을 찾을 수 없습니다")

    # symbols_legend.json 에서 직접 로드 (이미지 경로 포함)
    session_dir = OUTPUT_DIR / session_id
    json_path = session_dir / "symbols_legend.json"

    if not json_path.exists():
        return {
            "session_id": session_id,
            "total": 0,
            "categories": {},
            "symbols": [],
        }

    with open(json_path) as f:
        all_symbols = json.load(f)

    # 이미지 URL 생성
    for sym in all_symbols:
        img_filename = sym.get("image_filename")
        if img_filename:
            img_full = session_dir / "symbols" / img_filename
            if img_full.exists():
                sym["image_url"] = f"/api/symbols/{session_id}/image/{img_filename}"
            else:
                sym["image_url"] = None
        else:
            sym["image_url"] = None

    # 카테고리 집계 (필터 전)
    categories = {}
    for s in all_symbols:
        cat = s.get("category", "OTHER")
        categories[cat] = categories.get(cat, 0) + 1

    # 필터 적용
    filtered = all_symbols
    if category:
        filtered = [s for s in filtered if s.get("category", "").upper() == category.upper()]
    if search:
        q = search.lower()
        filtered = [
            s for s in filtered
            if q in (s.get("description") or "").lower()
            or q in (s.get("symbol_name") or "").lower()
        ]

    return {
        "session_id": session_id,
        "total": len(filtered),
        "total_all": len(all_symbols),
        "categories": categories,
        "symbols": filtered,
    }


@router.get("/symbols/{session_id}/image/{filename}")
async def get_symbol_image(session_id: str, filename: str):
    """개별 심볼 이미지 서빙"""
    file_path = OUTPUT_DIR / session_id / "symbols" / filename
    if not file_path.exists():
        file_path = OUTPUT_DIR / session_id / filename
    if not file_path.exists():
        raise HTTPException(404, f"심볼 이미지를 찾을 수 없습니다: {filename}")

    return FileResponse(
        str(file_path),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )
