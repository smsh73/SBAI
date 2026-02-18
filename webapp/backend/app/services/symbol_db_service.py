"""P&ID 레전드 심볼 DB 구축 서비스 (VLM 기반)

P&ID PDF의 첫 번째 페이지(LEGEND SYMBOL & ABBREVIATION)에서
Claude Vision API를 사용하여 PIPING SYMBOLS, VALVE SYMBOLS 등을
정확하게 추출하고 개별 심볼 이미지를 크롭하여 DB에 저장.
"""
import anthropic
import base64
import fitz  # PyMuPDF
import json
import logging
import re
from pathlib import Path

from app.core.config import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
# 카테고리 상수
# ─────────────────────────────────────────
SYMBOL_CATEGORIES = [
    "PIPING", "VALVE", "ACTUATOR", "ACTUATED_VALVE",
    "SAFETY_DEVICE", "OTHER",
]

# 가비지 패턴 (필터링 대상)
GARBAGE_PATTERNS = [
    r"^[A-K]$",
    r"^1[0-6]$|^[1-9]$",
    r"^(SYMBOL|DESCRIPTION|DISCRIPTION|SYMBOLS?)$",
    r"^(SHIP NO|CLIENT|DRAWING|REV\b|DATE|SCALE|CHECKED|APPROVED)",
    r"^(AA\s*AA|NAN$|NN\")",
    r"^\s*$",
    r"^INSTRUMENT$",
    r"^LEGEND SYMBOL",
]

# ─────────────────────────────────────────
# VLM 프롬프트
# ─────────────────────────────────────────
LEGEND_ANALYSIS_PROMPT = """You are an expert P&ID (Piping and Instrumentation Diagram) engineer.
You are analyzing the LEGEND PAGE (page 1) of a P&ID drawing package for a ship/plant.

This page contains a SYMBOL LEGEND organized in columns/sections:

## SECTIONS (left to right):
1. PIPING SYMBOLS (leftmost column) - Strainers, screens, vents, drains, expansion joints, sounding caps, deck scuppers, valves-as-piping-accessories
2. VALVE SYMBOLS (second column) - Ball valve, gate valve, globe valve, check valve, needle valve, butterfly valve, plug valve, diaphragm valve, etc. in OPEN/CLOSED states
3. ACTUATORS (third column, top area) - Hand operator, diaphragm/membrane, piston, motor, hydraulic actuators
4. ACTUATED VALVES (third column, middle area) - Manual angle choke, control valves (general/modulating), self-contained pressure valves, isolation valves, solenoid valves (2/3/4 way)
5. SAFETY DEVICE SYMBOLS (third column, bottom area) - Pressure relief/safety valves (conventional, balanced bellow, pilot), pressure/vacuum valve, rupture disc, vacuum relief
6. OTHER SYMBOLS (rightmost column) - Flowmeters (coriolis, magnetic, venturi, vortex, turbine, ultrasonic, pitot), orifice plates, diaphragm seal, capacitance sensor, steam traps, horn/hooter

Each symbol entry consists of:
- A SYMBOL GRAPHIC (small technical drawing/icon) on the LEFT side
- A DESCRIPTION TEXT on the RIGHT side (e.g., "BALL VALVE (OPEN)", "GATE VALVE (CLOSED)")

## YOUR TASK:
Extract EVERY single symbol entry from ALL sections. For each symbol provide:

1. **category**: One of: PIPING, VALVE, ACTUATOR, ACTUATED_VALVE, SAFETY_DEVICE, OTHER
2. **symbol_name**: Short abbreviation/code if visible next to the symbol (e.g., "TS", "F", "M", "H", "AS", "C", "V", "R"). Empty string if no code is shown.
3. **description**: Full description text exactly as written (e.g., "BALL VALVE (OPEN)", "TEMPORARY STRAINER", "PRESSURE RELIEF/SAFETY VALVE (CONVENTIONAL)")
4. **bbox_pct**: Bounding box of the SYMBOL GRAPHIC ONLY (not the description text) as [x1_pct, y1_pct, x2_pct, y2_pct] where values are fractions (0.0 to 1.0) of the full page width and height. The box should tightly enclose just the graphical symbol/icon.

## CRITICAL RULES:
1. Extract ALL symbols from ALL sections. Target: approximately 120-150 symbols total.
2. Multi-line descriptions MUST be merged into ONE entry. Examples:
   - "PRESSURE RELIEF/SAFETY VALVE" + "(CONVENTIONAL) (NOTE1)" → single entry: "PRESSURE RELIEF/SAFETY VALVE (CONVENTIONAL) (NOTE1)"
   - "SELF CONTAINED PRESSURE (CONTROL)" + "VALVE WITH INTERNAL IMPULSE LINE" + "(DOWNSTREAM)" → single entry
   - "SOUNDING CAP SELF CLOSING WEIGHT" + "WITH SELF CLOSING COCK" → single entry
3. Do NOT include section headers ("PIPING SYMBOLS", "VALVE SYMBOLS", "ACTUATORS", etc.)
4. Do NOT include column headers ("SYMBOL", "DESCRIPTION", "DISCRIPTION")
5. Do NOT include table grid border labels (single letters A-K, numbers 1-16)
6. Do NOT include title block text (SHIP NO., CLIENT, DRAWING NO., REV, SCALE, etc.)
7. For each valve that has OPEN and CLOSED variants, create SEPARATE entries for each.
8. For "DOUBLE BLOCK AND BLEED" variants (general, ball valve, needle valve, plug valve, integrated), create SEPARATE entries.
9. The bbox_pct should cover only the GRAPHIC SYMBOL area to the LEFT of the description text.

Return ONLY a valid JSON array (no markdown fences, no commentary):
[
  {"category": "PIPING", "symbol_name": "TS", "description": "TEMPORARY STRAINER", "bbox_pct": [0.02, 0.06, 0.08, 0.08]},
  {"category": "VALVE", "symbol_name": "", "description": "BALL VALVE (OPEN)", "bbox_pct": [0.23, 0.06, 0.30, 0.08]},
  ...
]"""


# ─────────────────────────────────────────
# 메인 추출 함수
# ─────────────────────────────────────────
def extract_symbols_from_legend(pdf_path: str, output_dir: str) -> list[dict]:
    """P&ID PDF 첫 페이지에서 심볼 레전드 추출 (VLM + 이미지 크롭)

    Returns:
        list of {id, category, symbol_name, description, image_path, image_filename, bbox_pct}
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    symbols_dir = out / "symbols"
    symbols_dir.mkdir(exist_ok=True)

    try:
        # Phase 1: 렌더링
        vlm_path, hires_path, page_w, page_h, scale = _render_legend_page(
            pdf_path, str(out))
        logger.info(f"Legend page rendered: {page_w:.0f}x{page_h:.0f}pt, scale={scale:.1f}")

        # Phase 2: VLM 분석
        symbols = _analyze_legend_with_vlm(vlm_path)
        logger.info(f"VLM extracted {len(symbols)} raw symbols")

        # Phase 3: 검증 & 정리
        symbols = _validate_and_clean(symbols)
        logger.info(f"After cleanup: {len(symbols)} symbols")

        # Phase 4: 이미지 크롭 (text-position based)
        symbols = _crop_symbol_images(symbols, hires_path, str(symbols_dir), pdf_path)
        cropped = sum(1 for s in symbols if s.get("image_filename"))
        logger.info(f"Symbol images cropped: {cropped}/{len(symbols)}")

    except Exception as e:
        logger.warning(f"VLM symbol extraction failed, falling back to text: {e}")
        symbols = _extract_text_fallback(pdf_path, str(out))

    # ID 할당 & JSON 저장
    for idx, sym in enumerate(symbols, 1):
        sym["id"] = idx

    json_path = out / "symbols_legend.json"
    with open(json_path, "w") as f:
        json.dump(symbols, f, ensure_ascii=False, indent=2)

    by_cat = {}
    for s in symbols:
        cat = s.get("category", "OTHER")
        by_cat[cat] = by_cat.get(cat, 0) + 1
    logger.info(f"Symbol extraction complete: {len(symbols)} total, by category: {by_cat}")

    return symbols


# ─────────────────────────────────────────
# Phase 1: 렌더링
# ─────────────────────────────────────────
def _render_legend_page(pdf_path: str, output_dir: str):
    """레전드 페이지(page 0)를 렌더링.

    Returns:
        (vlm_image_path, hires_image_path, page_width_pt, page_height_pt, hires_scale)
    """
    doc = fitz.open(pdf_path)
    page = doc[0]
    pw, ph = page.rect.width, page.rect.height

    # 고해상도 (300 DPI) - 심볼 크롭용
    hires_dpi = 300
    hires_scale = hires_dpi / 72
    hires_mat = fitz.Matrix(hires_scale, hires_scale)
    hires_pix = page.get_pixmap(matrix=hires_mat)
    hires_path = str(Path(output_dir) / "legend_page_full.png")
    hires_pix.save(hires_path)

    # VLM용 (적정 해상도, 최대 5000px)
    max_dim = max(pw, ph)
    vlm_dpi = min(200, int(5000 / max_dim * 72))
    vlm_mat = fitz.Matrix(vlm_dpi / 72, vlm_dpi / 72)
    vlm_pix = page.get_pixmap(matrix=vlm_mat)
    vlm_path = str(Path(output_dir) / "legend_page_vlm.png")
    vlm_pix.save(vlm_path)

    logger.info(f"Legend renders: hires={hires_pix.width}x{hires_pix.height}, "
                f"vlm={vlm_pix.width}x{vlm_pix.height}")

    hires_pix = None
    vlm_pix = None
    doc.close()

    return vlm_path, hires_path, pw, ph, hires_scale


# ─────────────────────────────────────────
# Phase 2: VLM 분석
# ─────────────────────────────────────────
def _analyze_legend_with_vlm(vlm_image_path: str) -> list[dict]:
    """Claude Vision API로 레전드 페이지 분석."""
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not configured")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    with open(vlm_image_path, "rb") as f:
        img_data = base64.standard_b64encode(f.read()).decode("utf-8")

    content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": img_data,
            },
        },
        {"type": "text", "text": LEGEND_ANALYSIS_PROMPT},
    ]

    resp = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=16384,
        messages=[{"role": "user", "content": content}],
    )

    raw_text = resp.content[0].text.strip()
    stop_reason = resp.stop_reason
    logger.info(f"VLM response: {len(raw_text)} chars, stop_reason={stop_reason}")

    # Markdown fences 제거
    if raw_text.startswith("```"):
        raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
        raw_text = re.sub(r"\s*```$", "", raw_text)

    # JSON 파싱 시도 - 잘린 응답 복구
    try:
        symbols = json.loads(raw_text)
    except json.JSONDecodeError:
        # 잘린 JSON 복구 시도: 마지막 완전한 객체까지만 파싱
        logger.warning("JSON parse failed, attempting to recover truncated response")
        last_close = raw_text.rfind("}")
        if last_close > 0:
            truncated = raw_text[:last_close + 1]
            # 배열 닫기
            if not truncated.rstrip().endswith("]"):
                truncated = truncated.rstrip().rstrip(",") + "\n]"
            symbols = json.loads(truncated)

    # dict 래핑 처리
    if isinstance(symbols, dict):
        if "symbols" in symbols:
            symbols = symbols["symbols"]
        elif "data" in symbols:
            symbols = symbols["data"]
        else:
            raise ValueError(f"VLM returned unexpected dict keys: {list(symbols.keys())}")

    if not isinstance(symbols, list):
        raise ValueError(f"VLM returned non-list type: {type(symbols)}")

    return symbols


# ─────────────────────────────────────────
# Phase 3: 검증 & 정리
# ─────────────────────────────────────────
def _validate_and_clean(symbols: list[dict]) -> list[dict]:
    """가비지 제거, 중복 제거, 카테고리 정규화."""
    cleaned = []
    seen = set()

    for sym in symbols:
        desc = (sym.get("description") or "").strip()

        # 짧은 설명 스킵
        if len(desc) < 3:
            continue

        # 가비지 패턴 필터링
        skip = False
        for pattern in GARBAGE_PATTERNS:
            if re.match(pattern, desc, re.IGNORECASE):
                skip = True
                break
        if skip:
            continue

        # 카테고리 정규화
        cat = (sym.get("category") or "OTHER").upper().strip()
        cat = cat.replace(" ", "_")
        if cat not in SYMBOL_CATEGORIES:
            cat = "OTHER"
        sym["category"] = cat

        # symbol_name 정리
        sym["symbol_name"] = (sym.get("symbol_name") or "").strip()

        # 중복 제거 (description 기준, 대소문자 무시)
        desc_key = desc.upper()
        if desc_key in seen:
            continue
        seen.add(desc_key)

        sym["description"] = desc
        cleaned.append(sym)

    return cleaned


# ─────────────────────────────────────────
# Phase 4: 이미지 크롭
# ─────────────────────────────────────────
def _crop_symbol_images(symbols: list[dict], hires_path: str,
                        symbols_dir: str, pdf_path: str) -> list[dict]:
    """Text-position-based symbol cropping.

    Improvements over basic cropping:
    - Groups symbols by column and uses midpoint between consecutive symbols
      as row boundaries → full symbol height without clipping
    - Left/right insets (8pt / 5pt) to exclude vertical grid lines
    - Post-crop PIL-based vertical border trimming as safety net
    """
    from PIL import Image

    sym_dir = Path(symbols_dir)
    sym_dir.mkdir(parents=True, exist_ok=True)

    hires_img = Image.open(hires_path)
    img_w, img_h = hires_img.size

    doc = fitz.open(pdf_path)
    page = doc[0]
    pw, ph = page.rect.width, page.rect.height
    scale_x = img_w / pw
    scale_y = img_h / ph

    SYM_WIDTH_PT = 70      # Total width from description to left column border
    LEFT_INSET_PT = 8      # Inset from left column border to avoid vertical line
    RIGHT_INSET_PT = 5     # Inset from right (before description) to avoid vertical line

    MIN_HEIGHT_PT = 12     # Minimum crop height in points
    MAX_HEIGHT_PT = 60     # Maximum crop height (prevents multi-row capture)

    # ── First pass: find all text positions (with VLM bbox hint) ──
    text_rects: dict[int, fitz.Rect] = {}
    for idx, sym in enumerate(symbols):
        desc = (sym.get("description") or "").strip()
        if not desc:
            continue
        bbox_pct = sym.get("bbox_pct")
        hint = None
        if bbox_pct and len(bbox_pct) >= 4:
            hint = ((bbox_pct[0] + bbox_pct[2]) / 2, (bbox_pct[1] + bbox_pct[3]) / 2)
        rect = _find_text_on_page(page, desc, bbox_hint=hint)
        if rect:
            text_rects[idx] = rect

    # ── Group by column (x-proximity) and compute row boundaries ──
    entries = sorted(text_rects.items(), key=lambda e: (e[1].x0, e[1].y0))

    columns: list[list[tuple[int, fitz.Rect]]] = []
    for idx, rect in entries:
        placed = False
        for col in columns:
            if abs(rect.x0 - col[0][1].x0) < 50:
                col.append((idx, rect))
                placed = True
                break
        if not placed:
            columns.append([(idx, rect)])

    row_bounds: dict[int, tuple[float, float]] = {}
    for col in columns:
        col.sort(key=lambda e: e[1].y0)
        for i, (idx, rect) in enumerate(col):
            # Top: midpoint with previous symbol
            if i > 0:
                prev_rect = col[i - 1][1]
                y_top = (prev_rect.y1 + rect.y0) / 2
            else:
                y_top = max(0, rect.y0 - 15)

            # Bottom: midpoint with next symbol
            if i < len(col) - 1:
                next_rect = col[i + 1][1]
                y_bottom = (rect.y1 + next_rect.y0) / 2
            else:
                y_bottom = min(ph, rect.y1 + 15)

            row_bounds[idx] = (y_top, y_bottom)

    # ── Second pass: crop images ──
    for idx, sym in enumerate(symbols):
        desc = (sym.get("description") or "").strip()
        if not desc:
            sym["image_path"] = None
            sym["image_filename"] = None
            continue

        text_rect = text_rects.get(idx)

        if text_rect:
            y_top, y_bottom = row_bounds.get(idx, (
                max(0, text_rect.y0 - 10),
                min(ph, text_rect.y1 + 10),
            ))
            # Enforce minimum / maximum height
            if y_bottom - y_top < MIN_HEIGHT_PT:
                center_y = (y_top + y_bottom) / 2
                y_top = max(0, center_y - MIN_HEIGHT_PT / 2)
                y_bottom = min(ph, center_y + MIN_HEIGHT_PT / 2)
            elif y_bottom - y_top > MAX_HEIGHT_PT:
                center_y = (text_rect.y0 + text_rect.y1) / 2
                y_top = max(0, center_y - MAX_HEIGHT_PT / 2)
                y_bottom = min(ph, center_y + MAX_HEIGHT_PT / 2)

            sym_x0 = max(0, text_rect.x0 - SYM_WIDTH_PT + LEFT_INSET_PT)
            sym_y0 = y_top
            sym_x1 = max(sym_x0 + 10, text_rect.x0 - RIGHT_INSET_PT)
            sym_y1 = y_bottom
        else:
            # Fallback: use VLM bbox with generous padding
            bbox_pct = sym.get("bbox_pct")
            if not bbox_pct or len(bbox_pct) != 4:
                sym["image_path"] = None
                sym["image_filename"] = None
                continue
            x1_pct, y1_pct, x2_pct, y2_pct = bbox_pct
            sym_x0 = max(0, x1_pct * pw - 5)
            sym_y0 = max(0, y1_pct * ph - 10)
            sym_x1 = min(pw, x2_pct * pw + 5)
            sym_y1 = min(ph, y2_pct * ph + 10)
            # Enforce min/max height for fallback too
            h_pt = sym_y1 - sym_y0
            if h_pt < MIN_HEIGHT_PT:
                cy = (sym_y0 + sym_y1) / 2
                sym_y0 = max(0, cy - MIN_HEIGHT_PT / 2)
                sym_y1 = min(ph, cy + MIN_HEIGHT_PT / 2)
            elif h_pt > MAX_HEIGHT_PT:
                cy = (sym_y0 + sym_y1) / 2
                sym_y0 = max(0, cy - MAX_HEIGHT_PT / 2)
                sym_y1 = min(ph, cy + MAX_HEIGHT_PT / 2)

        # Convert to hires pixels
        px0 = max(0, int(sym_x0 * scale_x))
        py0 = max(0, int(sym_y0 * scale_y))
        px1 = min(img_w, int(sym_x1 * scale_x))
        py1 = min(img_h, int(sym_y1 * scale_y))

        if (px1 - px0) < 15 or (py1 - py0) < 10:
            sym["image_path"] = None
            sym["image_filename"] = None
            continue

        cat = sym.get("category", "other").lower()
        img_filename = f"symbol_{idx + 1:03d}_{cat}.png"
        img_path = sym_dir / img_filename

        try:
            crop = hires_img.crop((px0, py0, px1, py1))
            crop = _trim_vertical_borders(crop)
            crop.save(str(img_path))
            sym["image_path"] = str(img_path)
            sym["image_filename"] = img_filename
        except Exception as e:
            logger.warning(f"Symbol crop failed [{idx + 1}]: {e}")
            sym["image_path"] = None
            sym["image_filename"] = None

    hires_img.close()
    doc.close()
    return symbols


def _trim_vertical_borders(img):
    """Remove vertical grid lines from left/right edges of cropped symbol image.

    Scans edge columns for predominantly dark pixel columns (indicating a grid line)
    and trims them with a small margin.
    """
    w, h = img.size
    if h < 10 or w < 20:
        return img

    gray = img.convert('L')
    pixels = gray.load()

    dark_threshold = 160
    line_ratio = 0.6   # Column with >60% dark pixels = grid line (not symbol part)
    max_check = min(25, w // 3)  # Scan up to 25px or 1/3 of width

    # Scan left region: find rightmost line column within range
    left = 0
    for x in range(max_check):
        dark_count = sum(1 for y in range(h) if pixels[x, y] < dark_threshold)
        if dark_count / h > line_ratio:
            left = x + 1

    # Scan right region: find leftmost line column within range
    right = w
    for x in range(w - 1, max(w - 1 - max_check, 0), -1):
        dark_count = sum(1 for y in range(h) if pixels[x, y] < dark_threshold)
        if dark_count / h > line_ratio:
            right = x

    # Add margin past the detected line
    if left > 0:
        left = min(left + 4, w // 3)
    if right < w:
        right = max(right - 4, w * 2 // 3)

    if left >= right:
        return img

    if left > 0 or right < w:
        return img.crop((left, 0, right, h))
    return img


def _find_text_on_page(page, description: str, bbox_hint=None):
    """Search for description text on the page using progressively shorter queries.

    Args:
        bbox_hint: Optional (x_pct, y_pct) from VLM bbox center.
                   When multiple matches found, picks the closest one.
    """
    desc = description.strip()
    pw, ph = page.rect.width, page.rect.height

    def _pick_best(instances):
        if not bbox_hint:
            return instances[0]
        hint_x = bbox_hint[0] * pw
        hint_y = bbox_hint[1] * ph
        best = min(instances, key=lambda r:
                   (r.x0 - hint_x) ** 2 + (r.y0 - hint_y) ** 2)
        # Reject if too far from hint (>25% of normalized page diagonal)
        dist_norm = (((best.x0 / pw - bbox_hint[0]) ** 2 +
                      (best.y0 / ph - bbox_hint[1]) ** 2) ** 0.5)
        if dist_norm > 0.25:
            return None
        return best

    # Try progressively shorter search strings
    for search_len in [40, 25, 16, 10]:
        search_text = desc[:search_len].strip()
        if len(search_text) < 5:
            continue
        instances = page.search_for(search_text)
        if instances:
            return _pick_best(instances)

    # Try individual significant words (skip short common words)
    words = [w for w in desc.split() if len(w) > 4]
    for word in words[:3]:
        instances = page.search_for(word)
        if instances:
            return _pick_best(instances)

    return None


# ─────────────────────────────────────────
# 폴백: 텍스트 기반 추출 (기존 로직 개선)
# ─────────────────────────────────────────
SECTION_HEADERS_TEXT = {
    "PIPING SYMBOLS": "PIPING",
    "VALVE SYMBOLS": "VALVE",
    "ACTURATORS": "ACTUATOR",
    "ACTUATORS": "ACTUATOR",
    "ACTURATED VALVES": "ACTUATED_VALVE",
    "ACTUATED VALVES": "ACTUATED_VALVE",
    "SAFETY DEVICE SYMBOLS": "SAFETY_DEVICE",
    "OTHER SYMBOLS": "OTHER",
    "INSTRUMENT VALVE BODIES": "ACTUATED_VALVE",
}


def _extract_text_fallback(pdf_path: str, output_dir: str) -> list[dict]:
    """VLM 실패 시 텍스트 기반 폴백 추출 (정리 필터 포함)."""
    doc = fitz.open(pdf_path)
    page = doc[0]
    page_width = page.rect.width
    page_height = page.rect.height

    symbols_dir = Path(output_dir) / "symbols"
    symbols_dir.mkdir(parents=True, exist_ok=True)

    # 고해상도 렌더링
    hires_dpi = 300
    scale = hires_dpi / 72
    hires_mat = fitz.Matrix(scale, scale)
    hires_pix = page.get_pixmap(matrix=hires_mat)

    # 텍스트 블록 추출
    blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
    text_lines = []
    for block in blocks:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                text = span["text"].strip()
                if not text:
                    continue
                bbox = span["bbox"]
                text_lines.append({
                    "x0": bbox[0], "y0": bbox[1],
                    "x1": bbox[2], "y1": bbox[3],
                    "text": text,
                    "font_size": span["size"],
                    "font_name": span["font"],
                    "is_bold": "Bold" in span["font"] or "bold" in span["font"],
                })

    # 섹션 헤더 식별
    sections = []
    for tl in text_lines:
        text_upper = tl["text"].upper().strip()
        for header_key, category in SECTION_HEADERS_TEXT.items():
            if header_key in text_upper:
                sections.append({
                    "category": category,
                    "x0": tl["x0"], "y0": tl["y0"],
                    "x1": tl["x1"], "y1": tl["y1"],
                })
                break

    sections.sort(key=lambda s: (s["x0"], s["y0"]))

    symbols = []
    for sec_idx, section in enumerate(sections):
        category = section["category"]
        x_left = section["x0"] - 60
        x_right = section["x1"] + 40

        next_sec_x = page_width
        for other in sections:
            if other["x0"] > section["x1"] + 50:
                next_sec_x = min(next_sec_x, other["x0"] - 10)
                break
        x_right = min(x_right, next_sec_x)

        y_start = section["y1"] + 5
        y_end = page_height - 50
        for other in sections:
            if (other["y0"] > section["y1"] + 20 and
                    abs(other["x0"] - section["x0"]) < 80):
                y_end = min(y_end, other["y0"] - 5)

        desc_lines = [
            tl for tl in text_lines
            if (x_left - 20 <= tl["x0"] <= x_right + 60 and
                y_start <= tl["y0"] <= y_end and
                tl["font_size"] < 6.5 and
                tl["text"].upper() not in ("SYMBOL", "DESCRIPTION", "SYMBOLS"))
        ]
        desc_lines.sort(key=lambda t: (round(t["y0"] / 3) * 3, t["x0"]))

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

        for row in rows:
            if not row:
                continue
            row.sort(key=lambda t: t["x0"])
            full_text = " ".join(t["text"] for t in row).strip()
            if len(full_text) < 3:
                continue
            if re.match(r"^[A-K]$", full_text) or re.match(r"^1[0-6]$|^[1-9]$", full_text):
                continue

            symbol_name = ""
            description = full_text
            if len(row) >= 2 and len(row[0]["text"]) <= 8 and len(row[-1]["text"]) > 8:
                symbol_name = row[0]["text"].strip()
                description = " ".join(t["text"] for t in row[1:]).strip()

            row_y_min = min(t["y0"] for t in row) - 3
            row_y_max = max(t["y1"] for t in row) + 3
            row_x_min = min(t["x0"] for t in row)

            sym_x0 = max(0, x_left - 10)
            sym_y0 = max(0, row_y_min - 2)
            sym_x1 = min(page_width, row_x_min - 2)
            sym_y1 = min(page_height, row_y_max + 2)

            px0, py0 = int(sym_x0 * scale), int(sym_y0 * scale)
            px1, py1 = int(sym_x1 * scale), int(sym_y1 * scale)

            img_filename = None
            img_path = None
            if px1 - px0 > 10 and py1 - py0 > 5:
                sid = len(symbols) + 1
                img_filename = f"symbol_{sid:03d}_{category.lower()}.png"
                img_full_path = symbols_dir / img_filename
                try:
                    crop_rect = fitz.IRect(px0, py0, px1, py1)
                    crop_pix = fitz.Pixmap(hires_pix, crop_rect)
                    crop_pix.save(str(img_full_path))
                    crop_pix = None
                    img_path = str(img_full_path)
                except Exception:
                    img_filename = None

            symbols.append({
                "category": category,
                "symbol_name": symbol_name,
                "description": description,
                "image_path": img_path,
                "image_filename": img_filename,
                "bbox_pct": [
                    sym_x0 / page_width, sym_y0 / page_height,
                    sym_x1 / page_width, sym_y1 / page_height,
                ],
            })

    hires_pix = None
    doc.close()

    # 정리 필터 적용
    symbols = _validate_and_clean(symbols)
    return symbols


# ─────────────────────────────────────────
# VLM 참조 텍스트 생성 (기존 호환)
# ─────────────────────────────────────────
def get_symbol_reference_text(symbols: list[dict]) -> str:
    """심볼 데이터를 VLM 프롬프트용 참조 텍스트로 변환."""
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
