"""파일 업로드 & 처리 라우터"""
import uuid
import asyncio
import logging
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, BackgroundTasks, HTTPException
from app.core.config import UPLOAD_DIR, OUTPUT_DIR, TEMPLATE_DIR
from app.services import dxf_service, pid_service, pipe_bom_service, excel_service, db_service

logger = logging.getLogger(__name__)
router = APIRouter()


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
    session_dir = OUTPUT_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    try:
        if file_type == "dxf":
            result = dxf_service.process_dxf(file_path, str(session_dir))
            await db_service.save_dimensions(session_id, result["dimensions"])

        elif file_type == "pid":
            # 밸브 추출
            valves = pid_service.extract_valves(file_path)
            # DB 저장
            await db_service.save_valves(session_id, valves)
            # Excel 생성
            excel_path = str(session_dir / "valve_list.xlsx")
            template = TEMPLATE_DIR / "2. 260210-VALVE-LIST-양식-외부송부용.xlsx"
            template_str = str(template) if template.exists() else None
            excel_service.generate_valve_excel(valves, excel_path, template_str)
            # P&ID 페이지 렌더링
            pid_service.render_pid_pages(file_path, str(session_dir))
            # JSON 저장
            import json
            with open(session_dir / "valve_data.json", "w") as f:
                json.dump(valves, f, ensure_ascii=False, indent=2)

        elif file_type == "pipe_bom":
            # BOM 추출
            pages_data = pipe_bom_service.extract_pipe_bom(file_path)
            # DB 저장
            await db_service.save_pipe_bom(session_id, pages_data)
            # Excel 생성
            excel_path = str(session_dir / "pipe_bom.xlsx")
            excel_service.generate_pipe_bom_excel(pages_data, excel_path)
            # BOM 페이지 렌더링
            pipe_bom_service.render_bom_pages(file_path, str(session_dir))
            # JSON 저장
            import json
            with open(session_dir / "pipe_bom_data.json", "w") as f:
                json.dump(pages_data, f, ensure_ascii=False, indent=2)

        elif file_type == "pdf":
            # 일반 PDF - 양쪽 모두 시도
            valves = pid_service.extract_valves(file_path)
            pages_data = pipe_bom_service.extract_pipe_bom(file_path)

            if valves:
                await db_service.save_valves(session_id, valves)
                excel_path = str(session_dir / "valve_list.xlsx")
                excel_service.generate_valve_excel(valves, excel_path)
                pid_service.render_pid_pages(file_path, str(session_dir))

            if any(pd.get("pipe_pieces") for pd in pages_data):
                await db_service.save_pipe_bom(session_id, pages_data)
                excel_path = str(session_dir / "pipe_bom.xlsx")
                excel_service.generate_pipe_bom_excel(pages_data, excel_path)

        await db_service.update_session_status(session_id, "completed")
        logger.info(f"Session {session_id} processing completed")

    except Exception as e:
        logger.error(f"Session {session_id} processing failed: {e}", exc_info=True)
        await db_service.update_session_status(session_id, f"error: {str(e)[:200]}")


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
