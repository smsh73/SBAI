"""파일 다운로드 라우터"""
import zipfile
import io
import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from app.core.config import OUTPUT_DIR
from app.services.db_service import get_session_info

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/download/{session_id}/{filename}")
async def download_file(session_id: str, filename: str):
    """개별 파일 다운로드"""
    session = await get_session_info(session_id)
    if not session:
        raise HTTPException(404, "세션을 찾을 수 없습니다")

    file_path = OUTPUT_DIR / session_id / filename
    if not file_path.exists():
        raise HTTPException(404, f"파일을 찾을 수 없습니다: {filename}")

    return FileResponse(
        str(file_path),
        filename=filename,
        media_type="application/octet-stream",
    )


@router.get("/download/{session_id}")
async def download_all(session_id: str):
    """전체 결과 ZIP 다운로드"""
    session = await get_session_info(session_id)
    if not session:
        raise HTTPException(404, "세션을 찾을 수 없습니다")

    session_dir = OUTPUT_DIR / session_id
    if not session_dir.exists():
        raise HTTPException(404, "결과 파일이 없습니다")

    # ZIP 생성
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in session_dir.iterdir():
            if f.is_file():
                zf.write(f, f.name)

    zip_buffer.seek(0)
    zip_name = f"SBAI_{session.get('file_name', session_id)}.zip"

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={zip_name}"},
    )
