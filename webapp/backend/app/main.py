"""SBAI FastAPI Application - SB선보 P&ID 도면 AI 변환 시스템"""
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import UPLOAD_DIR, OUTPUT_DIR
from app.routers import upload, results, download, chat
from app.services.db_service import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

app = FastAPI(
    title="SBAI - SB선보 P&ID 도면 AI 변환 시스템",
    version="1.0.0",
    description="P&ID 도면 업로드 → AI 분석 → 밸브/BOM 추출 → Excel 생성",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static file serving for outputs
app.mount("/static/outputs", StaticFiles(directory=str(OUTPUT_DIR)), name="outputs")

# Routers
app.include_router(upload.router, prefix="/api")
app.include_router(results.router, prefix="/api")
app.include_router(download.router, prefix="/api")
app.include_router(chat.router, prefix="/api")


@app.on_event("startup")
async def startup():
    await init_db()


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "sbai-backend"}
