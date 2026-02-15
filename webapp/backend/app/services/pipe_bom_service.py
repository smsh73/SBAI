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

# 표지 페이지 감지용 키워드
COVER_KEYWORDS = ["INDEX", "TABLE OF CONTENTS", "목차", "COVER", "DRAWING LIST"]


def _is_cover_page(text: str) -> bool:
    """표지/목차 페이지 여부 판단"""
    text_upper = text.upper()
    # 파이프 피스가 하나도 없고, 표지 키워드가 있으면 표지
    pieces = PIPE_PIECE_PATTERN.findall(text)
    valid_pieces = [p for p in pieces if len(p) >= 4 and any(c.isdigit() for c in p)
                    and not p.startswith(("REV", "DWG", "ISO", "PAGE"))]
    if not valid_pieces:
        for kw in COVER_KEYWORDS:
            if kw in text_upper:
                return True
    return False


def extract_pipe_bom(pdf_path: str) -> list[dict]:
    """PIPE BOM PDF에서 전체 데이터 추출 (모든 페이지)"""
    doc = fitz.open(pdf_path)
    pages_data = []
    total_pages = len(doc)

    logger.info(f"Processing PIPE BOM PDF: {pdf_path} ({total_pages} pages)")

    for page_num in range(total_pages):
        page = doc[page_num]
        text = page.get_text("text")
        blocks = page.get_text("blocks")

        # 표지 페이지 스킵 (데이터는 기록하되 is_cover 플래그)
        is_cover = _is_cover_page(text) if page_num == 0 else False

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
            "is_cover": is_cover,
        }

        if is_cover:
            pages_data.append(page_data)
            continue

        # 파이프 피스 추출
        pieces = PIPE_PIECE_PATTERN.findall(text)
        valid_pieces = []
        for p in pieces:
            if len(p) >= 4 and any(c.isdigit() for c in p):
                if not p.startswith(("REV", "DWG", "ISO", "PAGE")):
                    valid_pieces.append(p)
        page_data["pipe_pieces"] = list(dict.fromkeys(valid_pieces))

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

        if (page_num + 1) % 10 == 0:
            logger.info(f"  Extracted page {page_num + 1}/{total_pages}")

    doc.close()
    content_pages = sum(1 for p in pages_data if not p.get("is_cover") and p.get("pipe_pieces"))
    logger.info(f"Extracted BOM data: {total_pages} total pages, {content_pages} content pages with pipe pieces")
    return pages_data


def render_bom_pages(pdf_path: str, output_dir: str, dpi: int = 0, max_pages: int = 0) -> list[str]:
    """PIPE BOM PDF 페이지를 이미지로 렌더링 (전체 페이지)

    dpi: 0이면 페이지 수에 따라 자동 결정 (<=10: 200, <=30: 150, >30: 120)
    max_pages: 0이면 전체 페이지 렌더링
    """
    doc = fitz.open(pdf_path)
    total = len(doc)
    results = []

    # 페이지 수에 따라 DPI 자동 조절
    if dpi <= 0:
        if total <= 10:
            dpi = 200
        elif total <= 30:
            dpi = 150
        else:
            dpi = 120

    render_count = min(total, max_pages) if max_pages > 0 else total
    logger.info(f"Rendering {render_count} BOM pages at {dpi} DPI from {pdf_path}")

    for i in range(render_count):
        page = doc[i]
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        out_path = Path(output_dir) / f"bom_page{i+1}.png"
        pix.save(str(out_path))
        pix = None  # 메모리 해제
        results.append(str(out_path))

        if (i + 1) % 10 == 0:
            logger.info(f"  Rendered page {i+1}/{render_count}")

    doc.close()
    logger.info(f"Rendered {len(results)} BOM pages")
    return results
