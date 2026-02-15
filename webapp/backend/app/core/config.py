"""SBAI Configuration - 환경변수 설정"""
import os
from pathlib import Path

# Directories
BASE_DIR = Path(__file__).resolve().parent.parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
DB_DIR = BASE_DIR / "data"
TEMPLATE_DIR = BASE_DIR.parent.parent  # SBAI root for templates

UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
DB_DIR.mkdir(exist_ok=True)

# Database
SQLITE_DB_PATH = DB_DIR / "sbai.db"

# API Keys
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# DXF rendering
DIMLFAC = 75.01875305175781  # DXF dimension scale factor (drawing units → mm)

# File size limits
MAX_UPLOAD_SIZE_MB = 100
