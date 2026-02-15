"""처리 결과 조회 라우터"""
import json
import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from app.core.config import OUTPUT_DIR
from app.services.db_service import get_session_info, execute_query

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/results/{session_id}")
async def get_results(session_id: str):
    """처리 결과 조회 - 상태, 파일 목록, 데이터 미리보기"""
    session = await get_session_info(session_id)
    if not session:
        raise HTTPException(404, "세션을 찾을 수 없습니다")

    session_dir = OUTPUT_DIR / session_id
    files = []
    images = []
    excel_files = []
    json_files = []

    if session_dir.exists():
        for f in sorted(session_dir.iterdir()):
            rel_path = f"/static/outputs/{session_id}/{f.name}"
            entry = {"name": f.name, "path": rel_path, "size": f.stat().st_size}

            if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".svg"):
                images.append(entry)
            elif f.suffix.lower() in (".xlsx", ".xls"):
                excel_files.append(entry)
            elif f.suffix.lower() == ".json":
                json_files.append(entry)

            files.append(entry)

    # 데이터 미리보기
    preview = {}
    file_type = session.get("file_type", "")

    if file_type == "dxf" or file_type == "pdf":
        # 치수 데이터
        dim_path = session_dir / "dimensions.json"
        if dim_path.exists():
            with open(dim_path) as f:
                preview["dimensions"] = json.load(f)

    # 밸브 데이터 미리보기
    valve_path = session_dir / "valve_data.json"
    if valve_path.exists():
        with open(valve_path) as f:
            valves = json.load(f)
        preview["valves"] = {
            "total": len(valves),
            "by_type": {},
            "by_size": {},
            "sample": valves[:5],
        }
        for v in valves:
            vt = v.get("valve_type", "Unknown")
            preview["valves"]["by_type"][vt] = preview["valves"]["by_type"].get(vt, 0) + 1
            sz = v.get("size", "?")
            preview["valves"]["by_size"][sz] = preview["valves"]["by_size"].get(sz, 0) + 1

    # BOM 데이터 미리보기 (전체 페이지 데이터 포함)
    bom_path = session_dir / "pipe_bom_data.json"
    if bom_path.exists():
        with open(bom_path) as f:
            bom_data = json.load(f)
        total_welds = sum(pd.get("weld_count", 0) for pd in bom_data)
        total_pieces = sum(len(pd.get("pipe_pieces", [])) for pd in bom_data)
        content_pages = [pd for pd in bom_data if pd.get("pipe_pieces")]
        total_dims = sum(sum(pd.get("dimensions_mm", [])) for pd in bom_data)
        loose_count = sum(1 for pd in bom_data if pd.get("has_loose"))
        preview["pipe_bom"] = {
            "total_pages": len(bom_data),
            "content_pages": len(content_pages),
            "total_pieces": total_pieces,
            "total_welds": total_welds,
            "total_length_mm": total_dims,
            "loose_count": loose_count,
            "pages": bom_data,
        }

    return {
        "session_id": session_id,
        "status": session.get("status", "unknown"),
        "file_type": file_type,
        "file_name": session.get("file_name", ""),
        "files": files,
        "images": images,
        "excel_files": excel_files,
        "json_files": json_files,
        "preview": preview,
    }


@router.get("/results/{session_id}/image/{filename}")
async def get_image(session_id: str, filename: str):
    """이미지 파일 직접 반환"""
    file_path = OUTPUT_DIR / session_id / filename
    if not file_path.exists():
        raise HTTPException(404, "파일을 찾을 수 없습니다")
    return FileResponse(str(file_path))
