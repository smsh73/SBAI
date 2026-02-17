"""P&ID 레전드 심볼 DB 구축 서비스

P&ID PDF의 첫 번째 페이지(LEGEND SYMBOL & ABBREVIATION)에서
PIPING SYMBOLS, VALVE SYMBOLS 등을 개별 추출하여 DB에 저장.
"""
import fitz  # PyMuPDF
import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# 섹션 헤더 키워드 → 카테고리 매핑
SECTION_HEADERS = {
    "PIPING SYMBOLS": "PIPING",
    "VALVE SYMBOLS": "VALVE",
    "ACTURATORS": "ACTUATOR",
    "ACTURATED VALVES": "ACTUATED_VALVE",
    "SAFETY DEVICE SYMBOLS": "SAFETY_DEVICE",
    "OTHER SYMBOLS": "OTHER",
    "INSTRUMENT VALVE BODIES": "INSTRUMENT_VALVE",
}


def extract_symbols_from_legend(pdf_path: str, output_dir: str) -> list[dict]:
    """P&ID PDF 첫 페이지에서 심볼 레전드 추출

    Returns:
        list of {category, symbol_name, description, image_path, bbox, row_y}
    """
    doc = fitz.open(pdf_path)
    page = doc[0]
    page_width = page.rect.width
    page_height = page.rect.height

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    symbols_dir = Path(output_dir) / "symbols"
    symbols_dir.mkdir(exist_ok=True)

    # 전체 페이지 고해상도 렌더링 (심볼 크롭용)
    full_dpi = 300
    full_mat = fitz.Matrix(full_dpi / 72, full_dpi / 72)
    full_pix = page.get_pixmap(matrix=full_mat)
    scale = full_dpi / 72

    # 텍스트 블록 추출 (위치 포함)
    blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]

    # 텍스트 라인 수집: (x0, y0, x1, y1, text, font_size, font_name, is_bold)
    text_lines = []
    for block in blocks:
        if block["type"] != 0:  # text block only
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                text = span["text"].strip()
                if not text:
                    continue
                bbox = span["bbox"]
                font_size = span["size"]
                font_name = span["font"]
                is_bold = "Bold" in font_name or "bold" in font_name
                text_lines.append({
                    "x0": bbox[0], "y0": bbox[1],
                    "x1": bbox[2], "y1": bbox[3],
                    "text": text,
                    "font_size": font_size,
                    "font_name": font_name,
                    "is_bold": is_bold,
                })

    # 섹션 헤더 식별 (Bold, 큰 폰트)
    sections = []
    for tl in text_lines:
        text_upper = tl["text"].upper().strip()
        for header_key, category in SECTION_HEADERS.items():
            if header_key in text_upper:
                sections.append({
                    "category": category,
                    "header": tl["text"],
                    "x0": tl["x0"], "y0": tl["y0"],
                    "x1": tl["x1"], "y1": tl["y1"],
                })
                break

    logger.info(f"Found {len(sections)} legend sections in P&ID page 1")

    # 섹션별 컬럼 영역 추정
    # 각 섹션의 X 범위를 기반으로 해당 섹션에 속하는 텍스트를 그룹화
    sections.sort(key=lambda s: (s["x0"], s["y0"]))

    # DESCRIPTION 텍스트를 수집하여 심볼-설명 쌍 구성
    # 방법: 각 섹션의 X 범위 내에서 Y 순서로 설명 텍스트를 수집
    symbols = []
    symbol_id = 0

    for sec_idx, section in enumerate(sections):
        category = section["category"]
        sec_x_center = (section["x0"] + section["x1"]) / 2

        # 이 섹션의 X 범위 결정 (다음 섹션까지, 또는 페이지 끝)
        x_left = section["x0"] - 60  # 심볼 영역은 헤더 왼쪽으로 확장
        x_right = section["x1"] + 40

        # 같은 X 대역에 있는 다른 섹션 확인
        next_sec_x = page_width
        for other_sec in sections:
            if other_sec["x0"] > section["x1"] + 50:
                next_sec_x = min(next_sec_x, other_sec["x0"] - 10)
                break

        x_right = min(x_right, next_sec_x)

        # Y 범위: 섹션 헤더 아래 ~ 페이지 하단 (또는 다음 섹션)
        y_start = section["y1"] + 5

        # 같은 X 대역에서 다음 섹션의 Y 찾기
        y_end = page_height - 50  # 타이틀 블록 제외
        for other_sec in sections:
            if (other_sec["y0"] > section["y1"] + 20 and
                    abs(other_sec["x0"] - section["x0"]) < 80):
                y_end = min(y_end, other_sec["y0"] - 5)

        # 이 섹션 영역 내의 설명 텍스트 수집 (일반 크기 폰트)
        desc_lines = []
        for tl in text_lines:
            if (x_left - 20 <= tl["x0"] <= x_right + 60 and
                    y_start <= tl["y0"] <= y_end and
                    tl["font_size"] < 6.5 and
                    tl["text"].upper() not in ("SYMBOL", "DESCRIPTION", "SYMBOLS")):
                # 제목 블록 텍스트 제외
                if tl["y0"] > page_height - 80 and tl["x0"] > page_width - 260:
                    continue
                desc_lines.append(tl)

        # 같은 Y 위치의 텍스트를 하나의 설명으로 병합
        desc_lines.sort(key=lambda t: (round(t["y0"] / 3) * 3, t["x0"]))

        # Y 근접 그룹화 (3pt 이내는 같은 행)
        rows = []
        current_row = []
        prev_y = -100

        for tl in desc_lines:
            if abs(tl["y0"] - prev_y) > 4:
                if current_row:
                    rows.append(current_row)
                current_row = [tl]
            else:
                current_row.append(tl)
            prev_y = tl["y0"]
        if current_row:
            rows.append(current_row)

        # 각 행에서 심볼명과 설명 분리
        for row in rows:
            if not row:
                continue

            # 행의 텍스트를 X 위치 기준으로 정렬
            row.sort(key=lambda t: t["x0"])

            # 모든 텍스트 결합
            full_text = " ".join(t["text"] for t in row).strip()

            # 너무 짧거나 숫자만인 경우 스킵
            if len(full_text) < 3 or full_text.replace(".", "").replace(" ", "").isdigit():
                continue

            # 경계선 그리드 레이블 스킵 (A-K, 1-16)
            if re.match(r'^[A-K]$', full_text) or re.match(r'^1[0-6]$|^[1-9]$', full_text):
                continue

            # SYMBOL 컬럼과 DESCRIPTION 컬럼 분리
            # 보통 왼쪽이 축약명, 오른쪽이 설명
            symbol_name = ""
            description = full_text

            if len(row) >= 2:
                # 첫 번째 텍스트가 짧으면 심볼 축약명
                if len(row[0]["text"]) <= 8 and len(row[-1]["text"]) > 8:
                    symbol_name = row[0]["text"].strip()
                    description = " ".join(t["text"] for t in row[1:]).strip()
                else:
                    description = full_text

            # 심볼 이미지 영역 크롭
            row_y_min = min(t["y0"] for t in row) - 3
            row_y_max = max(t["y1"] for t in row) + 3
            row_x_min = min(t["x0"] for t in row)

            # 심볼 그래픽은 텍스트 왼쪽에 위치
            sym_crop_x0 = max(0, x_left - 10)
            sym_crop_y0 = max(0, row_y_min - 2)
            sym_crop_x1 = min(page_width, row_x_min - 2)
            sym_crop_y1 = min(page_height, row_y_max + 2)

            # 픽셀 좌표 변환
            px0 = int(sym_crop_x0 * scale)
            py0 = int(sym_crop_y0 * scale)
            px1 = int(sym_crop_x1 * scale)
            py1 = int(sym_crop_y1 * scale)

            # 유효한 크롭 영역인지 확인
            if px1 - px0 > 10 and py1 - py0 > 5:
                symbol_id += 1
                img_filename = f"symbol_{symbol_id:03d}_{category.lower()}.png"
                img_path = symbols_dir / img_filename

                # 심볼 이미지 크롭 및 저장
                try:
                    crop_rect = fitz.IRect(px0, py0, px1, py1)
                    crop_pix = fitz.Pixmap(full_pix, crop_rect)
                    crop_pix.save(str(img_path))
                    crop_pix = None
                except Exception:
                    img_path = None

                symbols.append({
                    "id": symbol_id,
                    "category": category,
                    "symbol_name": symbol_name,
                    "description": description,
                    "image_path": str(img_path) if img_path else None,
                    "bbox": [sym_crop_x0, sym_crop_y0, sym_crop_x1, sym_crop_y1],
                    "row_y": row_y_min,
                })

    full_pix = None
    doc.close()

    # JSON 저장
    json_path = Path(output_dir) / "symbols_legend.json"
    with open(json_path, "w") as f:
        json.dump(symbols, f, ensure_ascii=False, indent=2)

    logger.info(f"Extracted {len(symbols)} symbols from P&ID legend ({len(sections)} sections)")
    return symbols


def get_symbol_reference_text(symbols: list[dict]) -> str:
    """심볼 데이터를 VLM 프롬프트용 참조 텍스트로 변환"""
    ref_parts = []
    by_category = {}
    for sym in symbols:
        cat = sym["category"]
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(sym)

    for category, syms in by_category.items():
        ref_parts.append(f"\n### {category}")
        for s in syms:
            name = s.get("symbol_name", "")
            desc = s.get("description", "")
            if name:
                ref_parts.append(f"  - {name}: {desc}")
            else:
                ref_parts.append(f"  - {desc}")

    return "\n".join(ref_parts)
