"""PIPE BOM PDF에서 데이터 추출 서비스"""
import fitz  # PyMuPDF
import re
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 파이프 피스 패턴
PIPE_PIECE_PATTERN = re.compile(r'[A-Z]{1,3}\d{3,5}(?:-\d+)?(?:[A-Z])?')
WELD_PATTERN = re.compile(r'(?:FFW|W)\d+')
DIMENSION_PATTERN = re.compile(r'(\d{2,5})\s*(?:mm)?')
REVISION_PATTERN = re.compile(r'REV[.\s]*([A-Z0-9]+)', re.IGNORECASE)


def extract_pipe_bom(pdf_path: str) -> list[dict]:
    """PIPE BOM PDF에서 전체 데이터 추출"""
    doc = fitz.open(pdf_path)
    pages_data = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text("text")
        blocks = page.get_text("blocks")

        page_data = {
            "page": page_num + 1,
            "pipe_pieces": [],
            "weld_count": 0,
            "weld_items": [],
            "dimensions_mm": [],
            "other_dims": [],
            "has_loose": False,
            "revision_notes": [],
            "title_block": [],
            "table_text": [],
        }

        # 파이프 피스 추출
        pieces = PIPE_PIECE_PATTERN.findall(text)
        # 유효한 파이프 피스만 필터링 (보통 접두사가 있음)
        valid_pieces = []
        for p in pieces:
            if len(p) >= 4 and any(c.isdigit() for c in p):
                if not p.startswith(("REV", "DWG", "ISO", "PAGE")):
                    valid_pieces.append(p)
        page_data["pipe_pieces"] = list(dict.fromkeys(valid_pieces))  # 중복 제거, 순서 유지

        # 용접 항목 추출
        welds = WELD_PATTERN.findall(text)
        page_data["weld_items"] = welds
        page_data["weld_count"] = len(welds)

        # 치수 추출 (100~30000mm 범위)
        for dim_match in DIMENSION_PATTERN.finditer(text):
            val = int(dim_match.group(1))
            if 100 <= val <= 30000:
                page_data["dimensions_mm"].append(val)

        # LOOSE 파트 감지
        if "LOOSE" in text.upper():
            page_data["has_loose"] = True

        # 리비전 노트
        for rev_match in REVISION_PATTERN.finditer(text):
            page_data["revision_notes"].append(f"REV.{rev_match.group(1)}")

        # 블록 텍스트 수집
        for block in blocks:
            if len(block) >= 5:
                block_text = block[4].strip() if isinstance(block[4], str) else ""
                if block_text and len(block_text) > 2:
                    page_data["table_text"].append(block_text)

        pages_data.append(page_data)

    doc.close()
    logger.info(f"Extracted BOM data from {len(pages_data)} pages of {pdf_path}")
    return pages_data


def render_bom_pages(pdf_path: str, output_dir: str, dpi: int = 200, max_pages: int = 5) -> list[str]:
    """PIPE BOM PDF 페이지를 이미지로 렌더링"""
    doc = fitz.open(pdf_path)
    results = []
    for i in range(min(len(doc), max_pages)):
        page = doc[i]
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        out_path = Path(output_dir) / f"bom_page{i+1}.png"
        pix.save(str(out_path))
        results.append(str(out_path))
    doc.close()
    return results
