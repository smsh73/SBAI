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

    # VLM BOM 분석 결과 미리보기
    vlm_path = session_dir / "vlm_bom_data.json"
    if vlm_path.exists():
        with open(vlm_path) as f:
            vlm_data = json.load(f)
        total_vlm_pipes = sum(len(pd.get("pipe_pieces", [])) for pd in vlm_data)
        total_vlm_components = sum(len(pd.get("components", [])) for pd in vlm_data)
        total_vlm_welds = sum(len(pd.get("weld_points", [])) for pd in vlm_data)
        total_bom_items = sum(len(pd.get("bom_table", [])) for pd in vlm_data)
        total_vlm_dims = sum(len(pd.get("dimensions_mm", [])) for pd in vlm_data)
        total_cut_lengths = sum(len(pd.get("cut_lengths", [])) for pd in vlm_data)

        # 밸브/피팅 집계
        valve_summary = {}
        fitting_summary = {}
        line_nos = set()
        for pd in vlm_data:
            if pd.get("line_no"):
                line_nos.add(str(pd["line_no"]))
            for comp in pd.get("components", []):
                ctype = comp.get("type", "")
                subtype = comp.get("subtype", "unknown")
                qty = comp.get("quantity", 1)
                if ctype == "valve":
                    valve_summary[subtype] = valve_summary.get(subtype, 0) + qty
                elif ctype == "fitting":
                    fitting_summary[subtype] = fitting_summary.get(subtype, 0) + qty

        preview["vlm_bom"] = {
            "total_pages": len(vlm_data),
            "total_pipe_pieces": total_vlm_pipes,
            "total_components": total_vlm_components,
            "total_weld_points": total_vlm_welds,
            "total_bom_items": total_bom_items,
            "total_dimensions": total_vlm_dims,
            "total_cut_lengths": total_cut_lengths,
            "valve_summary": valve_summary,
            "fitting_summary": fitting_summary,
            "unique_line_nos": sorted(line_nos),
            "pages": vlm_data,
        }

    # 심볼 레전드 데이터
    symbols_path = session_dir / "symbols_legend.json"
    if symbols_path.exists():
        with open(symbols_path) as f:
            symbols = json.load(f)
        by_cat = {}
        for s in symbols:
            cat = s.get("category", "OTHER")
            by_cat[cat] = by_cat.get(cat, 0) + 1
            # 심볼 이미지 URL 추가
            img_fn = s.get("image_filename")
            if img_fn:
                s["image_url"] = f"/api/symbols/{session_id}/image/{img_fn}"
        preview["symbols"] = {
            "total": len(symbols),
            "by_category": by_cat,
            "categories": list(by_cat.keys()),
            "sample": symbols[:10],
        }

    # VLM 추출 통계
    stats_path = session_dir / "vlm_extraction_stats.json"
    if stats_path.exists():
        with open(stats_path) as f:
            preview["vlm_stats"] = json.load(f)

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
