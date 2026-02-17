"""파일 업로드 & 처리 라우터"""
import uuid
import asyncio
import logging
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, BackgroundTasks, HTTPException
from app.core.config import UPLOAD_DIR, OUTPUT_DIR, TEMPLATE_DIR
from app.services import (
    dxf_service, pid_service, pipe_bom_service,
    excel_service, db_service, symbol_db_service, vlm_bom_service,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# 심볼 레퍼런스 캐시 (P&ID 레전드에서 추출한 심볼 텍스트)
_symbol_ref_cache: str = ""


def _detect_file_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    name_lower = filename.lower()
    if ext == ".dxf":
        return "dxf"
    if ext == ".pdf":
        if "pid" in name_lower or "p&id" in name_lower or "valve" in name_lower:
            return "pid"
        if "bom" in name_lower or "pipe" in name_lower:
            return "pipe_bom"
        return "pdf"
    return "unknown"


async def _process_file(session_id: str, file_path: str, file_type: str, filename: str):
    """백그라운드 파일 처리"""
    global _symbol_ref_cache
    session_dir = OUTPUT_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    try:
        if file_type == "dxf":
            result = dxf_service.process_dxf(file_path, str(session_dir))
            await db_service.save_dimensions(session_id, result["dimensions"])

        elif file_type == "pid":
            # 1. 기존 밸브 추출
            valves = pid_service.extract_valves(file_path)
            await db_service.save_valves(session_id, valves)

            excel_path = str(session_dir / "valve_list.xlsx")
            template = TEMPLATE_DIR / "2. 260210-VALVE-LIST-양식-외부송부용.xlsx"
            template_str = str(template) if template.exists() else None
            excel_service.generate_valve_excel(valves, excel_path, template_str)
            pid_service.render_pid_pages(file_path, str(session_dir))

            import json
            with open(session_dir / "valve_data.json", "w") as f:
                json.dump(valves, f, ensure_ascii=False, indent=2)

            # 2. P&ID 레전드 심볼 추출 (첫 페이지)
            try:
                symbols = symbol_db_service.extract_symbols_from_legend(
                    file_path, str(session_dir))
                await db_service.save_symbols(session_id, symbols)

                # 심볼 레퍼런스 텍스트 캐시 (BOM 분석 시 사용)
                _symbol_ref_cache = symbol_db_service.get_symbol_reference_text(symbols)
                logger.info(f"Symbol reference cached: {len(symbols)} symbols")
            except Exception as e:
                logger.warning(f"Symbol extraction failed (non-critical): {e}")

        elif file_type == "pipe_bom":
            import json

            # 1. 기존 텍스트 기반 추출 (빠른 기본 데이터)
            pages_data = pipe_bom_service.extract_pipe_bom(file_path)
            await db_service.save_pipe_bom(session_id, pages_data)

            excel_path = str(session_dir / "pipe_bom.xlsx")
            excel_service.generate_pipe_bom_excel(pages_data, excel_path)

            # BOM 페이지 이미지 렌더링
            pipe_bom_service.render_bom_pages(file_path, str(session_dir))

            with open(session_dir / "pipe_bom_data.json", "w") as f:
                json.dump(pages_data, f, ensure_ascii=False, indent=2)

            # 2. VLM 정밀 분석 (Claude Vision)
            await db_service.update_session_status(session_id, "vlm_analyzing")
            try:
                vlm_results = vlm_bom_service.process_bom_with_vlm(
                    pdf_path=file_path,
                    output_dir=str(session_dir),
                    symbol_ref=_symbol_ref_cache,
                    text_extraction_data=pages_data,
                )
                await db_service.save_vlm_bom(session_id, vlm_results)

                # VLM 기반 정밀 Excel 생성
                vlm_excel_path = str(session_dir / "vlm_pipe_bom.xlsx")
                excel_service.generate_vlm_bom_excel(vlm_results, vlm_excel_path)

                with open(session_dir / "vlm_bom_data.json", "w") as f:
                    json.dump(vlm_results, f, ensure_ascii=False, indent=2)

                logger.info(f"VLM BOM analysis completed for session {session_id}")
            except Exception as e:
                logger.error(f"VLM BOM analysis failed: {e}", exc_info=True)
                # VLM 실패해도 기존 텍스트 추출 결과는 유지

        elif file_type == "pdf":
            import json
            # 일반 PDF - 양쪽 모두 시도
            valves = pid_service.extract_valves(file_path)
            pages_data = pipe_bom_service.extract_pipe_bom(file_path)

            if valves:
                await db_service.save_valves(session_id, valves)
                excel_path = str(session_dir / "valve_list.xlsx")
                excel_service.generate_valve_excel(valves, excel_path)
                pid_service.render_pid_pages(file_path, str(session_dir))

                # 심볼 추출 시도
                try:
                    symbols = symbol_db_service.extract_symbols_from_legend(
                        file_path, str(session_dir))
                    await db_service.save_symbols(session_id, symbols)
                    _symbol_ref_cache = symbol_db_service.get_symbol_reference_text(symbols)
                except Exception:
                    pass

            if any(pd.get("pipe_pieces") for pd in pages_data):
                await db_service.save_pipe_bom(session_id, pages_data)
                excel_path = str(session_dir / "pipe_bom.xlsx")
                excel_service.generate_pipe_bom_excel(pages_data, excel_path)

        await db_service.update_session_status(session_id, "completed")
        logger.info(f"Session {session_id} processing completed")

    except Exception as e:
        logger.error(f"Session {session_id} processing failed: {e}", exc_info=True)
        await db_service.update_session_status(session_id, f"error: {str(e)[:200]}")


@router.get("/sessions")
async def list_sessions():
    """세션 목록 조회 API"""
    sessions = await db_service.list_sessions()
    return {"sessions": sessions}


@router.post("/upload")
async def upload_file(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """파일 업로드 API"""
    if not file.filename:
        raise HTTPException(400, "파일명이 없습니다")

    session_id = str(uuid.uuid4())
    file_type = _detect_file_type(file.filename)

    if file_type == "unknown":
        raise HTTPException(400, f"지원하지 않는 파일 형식입니다: {file.filename}")

    # 파일 저장
    session_upload_dir = UPLOAD_DIR / session_id
    session_upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = session_upload_dir / file.filename

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    # DB 세션 생성
    await db_service.create_session(session_id, file_type, file.filename)

    # 백그라운드 처리
    background_tasks.add_task(_process_file, session_id, str(file_path), file_type, file.filename)

    return {
        "session_id": session_id,
        "file_name": file.filename,
        "file_type": file_type,
        "status": "processing",
        "message": f"파일 업로드 완료. 처리 중입니다. ({file_type})",
    }
