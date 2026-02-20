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
    r"^(AA\s*AA|NAN\b|NN\")",
    r"^\s*$",
    r"^INSTRUMENT$",
    r"^INSTRUMENT\s+VALVE\s+BODIES",
    r"^LEGEND SYMBOL",
    r"^MOTOR[\-\s]*HELMET",
    r"^(AA\s+)+",
    r"^(NN\"\s*)+$",
    r"^PIPING SYMBOLS",
    r"^VALVE SYMBOLS",
    r"^ACTUATORS?$",
    r"^ACTUATED\s+VALVES?$",
    r"^SAFETY\s+DEVICE",
    r"^OTHER\s+SYMBOLS?",
]

# ─────────────────────────────────────────
# VLM 프롬프트
# ─────────────────────────────────────────
LEGEND_ANALYSIS_PROMPT = """You are an expert P&ID (Piping and Instrumentation Diagram) engineer.
You are analyzing the LEGEND PAGE (page 1) of a P&ID drawing package for a ship/plant.

This page contains a SYMBOL LEGEND organized in columns/sections:

## SECTIONS (left to right):
1. PIPING SYMBOLS (leftmost area, split into 2 sub-columns):
   - Left sub-column: Reducers, nozzles, flanges, couplings, caps, hose connections, spectacle flanges, spades, spacers, removable spools, vents, drains, funnels, tees, sample connections, sight glass, expansion joints, bulkhead penetrations
   - Right sub-column: Strainers (temporary, conical, Y-type, T-type, basket), flame arrester, static mixer, straightening vane, air filter, mud/rose/drain boxes, liquid trap, flame/bug screens, vent heads, sounding caps, deck scuppers, silencer, bulkhead connector, quick closing valve, bellows expansion joint, self-closing valves, air release valve, hose connection valve, storm valve

2. VALVE SYMBOLS (second column) - Ball valve (open/closed/cryogenic), butterfly valve, gate valve (open/closed/with body drain), globe valve, screw down non-return valve, hose valve, lift/swing/dual flap check valves, needle valve (open/closed), angle valve, three-way valves (L-port/T-port), four-way valve, plug valve (open/closed), diaphragm valve, deluge valve, axial choke valve, split wedge gate valve (cryogenic), double block and bleed variants, foot valve, feed-through, flow control ball float

3. ACTUATORS (third column, top area) - Hand operator, diaphragm/membrane actuator, piston actuator, motor operated actuator, hydraulic operated actuator

4. ACTUATED VALVES (third column, middle area) - Instrument valve bodies section header (skip this), manual angle choke valve, control valve (general/modulating), manually control valve (general/isolating), self-contained pressure control valves (downstream/upstream variants), isolation valve (general) on/off, solenoid valves (2-way/3-way/3-way with mechanical reset/4-way), three-part hand valve

5. SAFETY DEVICE SYMBOLS (third column, bottom area) - Pressure relief/safety valves (conventional, balanced bellow, pilot) with (NOTE1), pressure/vacuum valve, rupture disc, vacuum relief valve/breaker valve

6. OTHER SYMBOLS (rightmost column) - Instrument air, flowmeters (coriolis, magnetic, venturi, vortex, turbine, positive displacement, ultrasonic in-line/clamp-on, pitot tube, averaging pitot tube, variable area), flow element orifice type with carrier, restriction orifice, dynamic variable orifice, diaphragm seal, capacitance sensor, calibration pot, horn/hooter, steam traps (regular, disc type with valve, float type)

Each symbol entry consists of:
- A SYMBOL GRAPHIC (small technical drawing/icon) on the LEFT side
- A DESCRIPTION TEXT on the RIGHT side (e.g., "BALL VALVE (OPEN)", "GATE VALVE (CLOSED)")

## YOUR TASK:
Extract EVERY single symbol entry from ALL sections. For each symbol provide:

1. **category**: One of: PIPING, VALVE, ACTUATOR, ACTUATED_VALVE, SAFETY_DEVICE, OTHER
2. **symbol_name**: Short abbreviation/code if visible INSIDE or NEAR the symbol graphic (e.g., "TS", "F", "M", "H", "AS", "C", "V", "R"). Empty string if no code is shown.
3. **description**: Full description text exactly as written on the drawing. Read CAREFULLY - do not guess or hallucinate text.
   - "CRYOGENIC" not "OPPOSING"
   - "BUTTERFLY VALVE" not "BUTTERFLY V-ALVE"
   - "ANGLE VALVE" not "SIMPLE VALVE"
   - "THREE-WAY VALVE (L-PORT)" and "THREE-WAY VALVE (T-PORT)" as separate entries
   - "ISOLATION VALVE (GENERAL), ON/OFF" not "SELF CON VALVE"
   - "THREE PART HAND VALVE" not "THREE PART HARD VALVE"
4. **bbox_pct**: Bounding box of the SYMBOL GRAPHIC ONLY (not the description text) as [x1_pct, y1_pct, x2_pct, y2_pct] where values are fractions (0.0 to 1.0) of the full page width and height. The box should tightly enclose just the graphical symbol/icon. Be PRECISE with the bounding box - it should NOT overlap with description text.

## CRITICAL RULES:
1. Extract ALL symbols from ALL sections. Target: approximately 120-150 symbols total.
2. Multi-line descriptions MUST be merged into ONE entry. Examples:
   - "PRESSURE RELIEF/SAFETY VALVE" + "(CONVENTIONAL) (NOTE1)" → single entry: "PRESSURE RELIEF/SAFETY VALVE (CONVENTIONAL) (NOTE1)"
   - "SELF CONTAINED PRESSURE (CONTROL)" + "VALVE WITH INTERNAL IMPULSE LINE" + "(DOWNSTREAM)" → single entry
   - "SOUNDING CAP SELF CLOSING WEIGHT" + "WITH SELF CLOSING COCK" → single entry
   - "CONTROL VALVE(GENERAL)," + "MODULATING" → single entry: "CONTROL VALVE(GENERAL), MODULATING"
   - "ISOLATION VALVE (GENERAL)," + "ON/OFF" → single entry: "ISOLATION VALVE (GENERAL), ON/OFF"
3. Do NOT include section headers ("PIPING SYMBOLS", "VALVE SYMBOLS", "ACTUATORS", "INSTRUMENT VALVE BODIES", etc.)
4. Do NOT include column headers ("SYMBOL", "DESCRIPTION", "DISCRIPTION")
5. Do NOT include table grid border labels (single letters A-K, numbers 1-16)
6. Do NOT include title block text (SHIP NO., CLIENT, DRAWING NO., REV, SCALE, etc.)
7. Do NOT include "AA AA" placeholder text or "NN" dimension placeholders
8. For each valve that has OPEN and CLOSED variants, create SEPARATE entries for each.
9. For "DOUBLE BLOCK AND BLEED" variants (general, ball valve, needle valve, plug valve, integrated), create SEPARATE entries.
10. The bbox_pct should cover ONLY the graphic symbol area to the LEFT of the description text.

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
    """Text-position-based symbol cropping with content-aware auto-trim.

    Pipeline: generous initial crop → grid line removal → auto-crop to content.
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

    SYM_WIDTH_PT = 70      # Symbol graphic width (reduced to avoid capturing description text)
    RIGHT_INSET_PT = 12    # Inset before description text (larger to prevent text bleed)
    MIN_HEIGHT_PT = 15     # Minimum crop height in points
    MAX_HEIGHT_PT = 120    # Maximum crop height (increased for compound symbols like DBB)
    EDGE_PAD_PT = 20       # Default padding for first/last items in column

    # ── Detect grid label zone (left margin of P&ID drawing frame) ──
    # Grid labels (A-K) sit at the left page margin; we must crop AFTER them.
    left_margin_x = 12.0   # Fallback minimum
    for c in "ABCDEFGHJK":
        for hr in page.search_for(c):
            # Single-char labels near the left page edge
            if hr.x0 < 45 and (hr.x1 - hr.x0) < 12:
                left_margin_x = max(left_margin_x, hr.x1 + 5)

    # ── Detect vertical grid lines from PDF vector paths ──
    # These define column boundaries more precisely than text positions
    vert_grid_lines: list[float] = []
    try:
        drawings = page.get_drawings()
        for d in drawings:
            for item in d.get("items", []):
                if item[0] == "l":  # line segment
                    p1, p2 = item[1], item[2]
                    # Vertical line: same x, spans significant height (>50% of page)
                    if abs(p1.x - p2.x) < 1.0 and abs(p1.y - p2.y) > ph * 0.3:
                        vert_grid_lines.append((p1.x + p2.x) / 2)
        vert_grid_lines = sorted(set(round(x, 1) for x in vert_grid_lines))
    except Exception:
        vert_grid_lines = []
    logger.info(f"Detected {len(vert_grid_lines)} vertical grid lines: {vert_grid_lines[:10]}")

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
            # Use median x0 of existing column members for comparison
            col_x_vals = [r.x0 for _, r in col]
            col_median_x = sorted(col_x_vals)[len(col_x_vals) // 2]
            if abs(rect.x0 - col_median_x) < 50:
                col.append((idx, rect))
                placed = True
                break
        if not placed:
            columns.append([(idx, rect)])
    # Sort columns left-to-right
    columns.sort(key=lambda col: min(r.x0 for _, r in col))

    # ── Compute per-column left boundary (using grid lines) ──
    col_left_boundary: dict[int, float] = {}
    for ci, col in enumerate(columns):
        col_min_x = min(r.x0 for _, r in col)
        # Find the nearest vertical grid line to the LEFT of this column's text
        best_grid = left_margin_x
        for gx in vert_grid_lines:
            if gx < col_min_x - 3 and gx > best_grid:
                # Ensure this grid line is close enough to be "our" column boundary
                if col_min_x - gx < SYM_WIDTH_PT + 30:
                    best_grid = gx
        col_left_boundary[ci] = best_grid + 3  # Small offset past the line
        logger.debug(f"Column {ci}: text_x={col_min_x:.1f}, left_bound={col_left_boundary[ci]:.1f}")

    # Collect ALL header/sub-header text rects on the page.
    # These are used both for per-column top-bound and per-symbol y_top clamping.
    all_header_rects: list[fitz.Rect] = []
    for header_text in ["SYMBOL", "DISCRIPTION", "DESCRIPTION"]:
        all_header_rects.extend(page.search_for(header_text))
    # Also collect section headers that appear mid-column
    for sec_hdr in ["INSTRUMENT VALVE BODIES", "SAFETY DEVICE SYMBOLS",
                     "ACTUATED VALVES", "ACTUATORS"]:
        all_header_rects.extend(page.search_for(sec_hdr))

    col_header_y1: dict[int, float] = {}
    for ci, col in enumerate(columns):
        col.sort(key=lambda e: e[1].y0)
        first_rect = col[0][1]
        for hr in all_header_rects:
            if (abs(hr.x0 - first_rect.x0) < 120 and
                    hr.y1 < first_rect.y0 and
                    first_rect.y0 - hr.y1 < 50):
                existing_y = col_header_y1.get(ci, 0)
                col_header_y1[ci] = max(existing_y, hr.y1)
        if ci in col_header_y1:
            break

    row_bounds: dict[int, tuple[float, float]] = {}
    sym_col_map: dict[int, int] = {}  # symbol idx → column index
    for ci, col in enumerate(columns):
        col.sort(key=lambda e: e[1].y0)
        for i, (idx, rect) in enumerate(col):
            sym_col_map[idx] = ci
            # Top: midpoint with previous symbol
            if i > 0:
                prev_rect = col[i - 1][1]
                y_top = (prev_rect.y1 + rect.y0) / 2
            else:
                # First item: use header bottom or default padding
                if ci in col_header_y1:
                    y_top = col_header_y1[ci] + 3
                else:
                    y_top = max(0, rect.y0 - EDGE_PAD_PT)

            # Bottom: midpoint with next symbol
            if i < len(col) - 1:
                next_rect = col[i + 1][1]
                y_bottom = (rect.y1 + next_rect.y0) / 2
            else:
                y_bottom = min(ph, rect.y1 + EDGE_PAD_PT)

            row_bounds[idx] = (y_top, y_bottom)

    # ── Clamp y_top past any header/sub-header text between y_top and symbol text ──
    # This handles mid-column sub-section headers like "INSTRUMENT VALVE BODIES"
    # with its own "SYMBOL" / "DESCRIPTION" sub-headers.
    for idx in list(row_bounds.keys()):
        text_rect = text_rects.get(idx)
        if not text_rect:
            continue
        y_top, y_bottom = row_bounds[idx]
        for hr in all_header_rects:
            if (abs(hr.x0 - text_rect.x0) < 150 and
                    hr.y0 >= y_top - 2 and hr.y1 < text_rect.y0 - 1):
                y_top = max(y_top, hr.y1 + 3)
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
            h_pt = y_bottom - y_top
            if h_pt < MIN_HEIGHT_PT:
                cy = (y_top + y_bottom) / 2
                y_top = max(0, cy - MIN_HEIGHT_PT / 2)
                y_bottom = min(ph, cy + MIN_HEIGHT_PT / 2)
            elif h_pt > MAX_HEIGHT_PT:
                cy = (text_rect.y0 + text_rect.y1) / 2
                y_top = max(0, cy - MAX_HEIGHT_PT / 2)
                y_bottom = min(ph, cy + MAX_HEIGHT_PT / 2)

            # Use per-column left boundary if available
            col_idx = sym_col_map.get(idx)
            col_left = col_left_boundary.get(col_idx, left_margin_x) if col_idx is not None else left_margin_x

            sym_x0 = max(col_left, text_rect.x0 - SYM_WIDTH_PT)
            sym_y0 = y_top

            # Clamp right edge: find minimum x0 of any description text
            # in overlapping Y range (prevents text bleed from adjacent rows)
            right_clamp = text_rect.x0
            for other_idx, other_rect in text_rects.items():
                if other_idx == idx:
                    continue
                if other_rect.y0 < y_bottom and other_rect.y1 > y_top:
                    if abs(other_rect.x0 - text_rect.x0) < 60:
                        right_clamp = min(right_clamp, other_rect.x0)
            sym_x1 = max(sym_x0 + 10, right_clamp - RIGHT_INSET_PT)
            sym_y1 = y_bottom
        else:
            # Fallback: use VLM bbox with generous padding
            bbox_pct = sym.get("bbox_pct")
            if not bbox_pct or len(bbox_pct) != 4:
                sym["image_path"] = None
                sym["image_filename"] = None
                continue
            x1_pct, y1_pct, x2_pct, y2_pct = bbox_pct
            sym_x0 = max(0, x1_pct * pw - 10)
            sym_y0 = max(0, y1_pct * ph - 15)
            sym_x1 = min(pw, x2_pct * pw + 10)
            sym_y1 = min(ph, y2_pct * ph + 15)
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
            crop = _whiten_gray_background(crop)
            crop = _trim_grid_borders(crop)
            crop = _auto_crop_to_content(crop, padding=6)
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


def _whiten_gray_background(img):
    """Convert gray background to white, preserving dark lines and text.

    Detects gray regions using two strategies:
    1. Overall edge median check (catches full gray backgrounds)
    2. Histogram-based check (catches partial gray backgrounds where
       a significant portion of pixels are in the gray range 180-240)
    """
    import numpy as np

    arr = np.array(img)
    if arr.ndim == 3:
        gray_arr = np.mean(arr, axis=2).astype(np.float32)
    else:
        gray_arr = arr.astype(np.float32)

    h, w = gray_arr.shape
    if h < 10 or w < 10:
        return img

    # Strategy 1: Check edge pixel median (catches full gray backgrounds)
    edges = np.concatenate([
        gray_arr[0, :], gray_arr[-1, :],
        gray_arr[:, 0], gray_arr[:, -1],
    ])
    bg_median = np.median(edges)

    do_whiten = False
    bg_value = bg_median

    if 180 <= bg_median <= 245:
        do_whiten = True

    # Strategy 2: Check if >15% of total pixels are in gray range 180-240
    # This catches partial gray backgrounds (e.g., left half gray, right half white)
    if not do_whiten:
        gray_band = (gray_arr >= 180) & (gray_arr <= 240)
        gray_frac = gray_band.sum() / gray_arr.size
        if gray_frac > 0.15:
            # Use the mode of gray-band pixels as the background value
            gray_pixels = gray_arr[gray_band]
            bg_value = np.median(gray_pixels)
            do_whiten = True

    if not do_whiten:
        return img

    # Replace pixels within ±25 of the detected gray value with white
    tolerance = 25
    low = bg_value - tolerance
    high = bg_value + tolerance

    if arr.ndim == 3:
        mask = (gray_arr >= low) & (gray_arr <= high)
        arr[mask] = [255, 255, 255]
    else:
        mask = (arr >= low) & (arr <= high)
        arr[mask] = 255

    from PIL import Image
    return Image.fromarray(arr)


def _trim_grid_borders(img):
    """Remove vertical and horizontal grid lines from edges of cropped symbol.

    Uses two-pass detection: first a strict pass for obvious grid lines,
    then a looser pass to catch thinner lines that span most of the image.
    """
    w, h = img.size
    if h < 10 or w < 20:
        return img

    gray = img.convert('L')
    pixels = gray.load()

    # Two-pass detection with different thresholds
    dark_threshold_strict = 180   # Catch lighter grid lines too
    dark_threshold_loose = 140    # For strong dark lines
    line_ratio_strict = 0.25      # Lower ratio to catch partial grid lines
    line_ratio_loose = 0.50       # Higher ratio for more conservative detection
    max_check_x = min(40, w // 3)
    max_check_y = min(30, h // 3)

    def _detect_vline(x_range, threshold, ratio):
        """Find rightmost/leftmost grid line in given x range."""
        best = -1
        for x in x_range:
            dark_count = sum(1 for y in range(h) if pixels[x, y] < threshold)
            if dark_count / h > ratio:
                best = x
        return best

    def _detect_hline(y_range, threshold, ratio):
        """Find bottommost/topmost grid line in given y range."""
        best = -1
        for y in y_range:
            dark_count = sum(1 for x in range(w) if pixels[x, y] < threshold)
            if dark_count / w > ratio:
                best = y
        return best

    # ── LEFT edge: detect vertical grid line ──
    left = 0
    # Strict pass (catches most grid lines)
    vl = _detect_vline(range(max_check_x), dark_threshold_strict, line_ratio_strict)
    if vl >= 0:
        left = vl + 1
    else:
        # Loose pass (catches strong dark lines only)
        vl = _detect_vline(range(min(15, w // 4)), dark_threshold_loose, line_ratio_loose)
        if vl >= 0:
            left = vl + 1

    # ── RIGHT edge: detect vertical grid line ──
    right = w
    vr = _detect_vline(range(w - 1, max(w - 1 - max_check_x, 0), -1),
                       dark_threshold_strict, line_ratio_strict)
    if vr >= 0:
        right = vr
    else:
        vr = _detect_vline(range(w - 1, max(w - 1 - 15, 0), -1),
                           dark_threshold_loose, line_ratio_loose)
        if vr >= 0:
            right = vr

    # ── TOP edge: detect horizontal grid line ──
    top = 0
    ht = _detect_hline(range(max_check_y), dark_threshold_strict, line_ratio_strict)
    if ht >= 0:
        top = ht + 1
    else:
        ht = _detect_hline(range(min(15, h // 4)), dark_threshold_loose, line_ratio_loose)
        if ht >= 0:
            top = ht + 1

    # ── BOTTOM edge: detect horizontal grid line ──
    bottom = h
    hb = _detect_hline(range(h - 1, max(h - 1 - max_check_y, 0), -1),
                       dark_threshold_strict, line_ratio_strict)
    if hb >= 0:
        bottom = hb
    else:
        hb = _detect_hline(range(h - 1, max(h - 1 - 15, 0), -1),
                           dark_threshold_loose, line_ratio_loose)
        if hb >= 0:
            bottom = hb

    # Add margins past detected lines (move further inward to avoid line residue)
    if left > 0:
        left = min(left + 6, w // 3)
    if right < w:
        right = max(right - 6, w * 2 // 3)
    if top > 0:
        top = min(top + 5, h // 3)
    if bottom < h:
        bottom = max(bottom - 5, h * 2 // 3)

    if left >= right or top >= bottom:
        return img

    if left > 0 or right < w or top > 0 or bottom < h:
        return img.crop((left, top, right, bottom))
    return img


def _auto_crop_to_content(img, padding=6):
    """Crop image to its actual visible content bounds with padding.

    Uses PIL to find the bounding box of non-white pixels, then checks
    for isolated edge content (grid labels, stray text) separated from
    the main symbol by a whitespace gap on all four edges.
    """
    from PIL import ImageOps
    import numpy as np

    gray = img.convert('L')
    binary = gray.point(lambda p: 0 if p < 235 else 255)
    inverted = ImageOps.invert(binary)
    bbox = inverted.getbbox()

    if not bbox:
        return img

    x_min, y_min, x_max, y_max = bbox
    w, h = img.size

    # Convert to numpy for faster scanning
    inv_arr = None
    try:
        inv_arr = __import__('numpy').array(inverted)
    except ImportError:
        pass

    def _col_has_content(x, ya, yb):
        if inv_arr is not None:
            return inv_arr[ya:yb, x].any()
        return any(inverted.getpixel((x, y)) > 0 for y in range(ya, yb))

    def _row_has_content(y, xa, xb):
        if inv_arr is not None:
            return inv_arr[y, xa:xb].any()
        return any(inverted.getpixel((x, y)) > 0 for x in range(xa, xb))

    gap_min_px = 3  # Minimum gap (px) to consider as separator (~0.7pt at 300 DPI)

    def _strip_edge_content(start, total_span, is_horizontal, is_forward, bound_min, bound_max):
        """Iteratively strip isolated content blocks separated by gaps.

        Scans along one axis looking for gap→content patterns. Each time a
        gap >= gap_min_px is found after content, the bound is moved past
        the gap. Repeats to handle multiple stacked text blocks (e.g.,
        "NN" → gap → "SYMBOL" → gap → actual symbol).

        Safeguard: never strip more than 40% of the total span to prevent
        removing the actual symbol content.
        """
        current_bound = start
        max_passes = 3
        max_strip = total_span * 2 // 5  # Never strip more than 40%

        for _pass in range(max_passes):
            # Check safeguard
            stripped_so_far = abs(current_bound - start)
            if stripped_so_far >= max_strip:
                break

            remaining = max_strip - stripped_so_far
            if is_forward:
                limit = min(current_bound + remaining, bound_max if is_horizontal else w)
                check_range = range(current_bound, limit)
            else:
                limit = max(current_bound - remaining, 0)
                check_range = range(current_bound, limit, -1)

            gap_start = -1
            found_content = False
            stripped = False
            for pos in check_range:
                if is_horizontal:
                    has_content = _row_has_content(pos, bound_min, bound_max)
                else:
                    has_content = _col_has_content(pos, bound_min, bound_max)

                if has_content:
                    found_content = True
                    if gap_start >= 0:
                        gap_size = abs(pos - gap_start)
                        if gap_size >= gap_min_px:
                            current_bound = pos
                            stripped = True
                            break
                    gap_start = -1
                else:
                    if found_content and gap_start < 0:
                        gap_start = pos
            if not stripped:
                break
        return current_bound

    content_w = x_max - x_min
    content_h = y_max - y_min

    # ── Strip isolated TOP-edge content FIRST (headers "SYMBOL", "NN" text) ──
    # Do top/bottom first so left/right scanning uses correct y range
    y_min = _strip_edge_content(
        y_min, content_h,
        is_horizontal=True, is_forward=True,
        bound_min=x_min, bound_max=x_max)

    # ── Strip isolated BOTTOM-edge content ──
    new_y_max = _strip_edge_content(
        y_max - 1, content_h,
        is_horizontal=True, is_forward=False,
        bound_min=x_min, bound_max=x_max)
    if new_y_max > y_min:
        y_max = new_y_max + 1 if new_y_max < y_max - 1 else y_max

    # ── Strip isolated LEFT-edge content (grid labels) ──
    # Single pass only (max_passes=1 via small total_span trick) to avoid
    # stripping small but valid symbols like flowmeter boxes [C], [M], [V]
    left_strip_span = (x_max - x_min) // 4  # Only scan first 25%
    gap_start_l = -1
    found_l = False
    for x in range(x_min, min(x_min + left_strip_span, w)):
        has_c = _col_has_content(x, y_min, y_max)
        if has_c:
            found_l = True
            if gap_start_l >= 0 and (x - gap_start_l) >= gap_min_px:
                x_min = x
                break
            gap_start_l = -1
        else:
            if found_l and gap_start_l < 0:
                gap_start_l = x

    # ── Strip isolated RIGHT-edge content (text fragments) ──
    # Scan up to 50% from right to catch description text bleed (e.g., "CORRIOL" from CORIOLIS)
    right_strip_span = (x_max - x_min) // 2
    gap_start_r = -1
    found_r = False
    for x in range(x_max - 1, max(x_max - 1 - right_strip_span, 0), -1):
        has_c = _col_has_content(x, y_min, y_max)
        if has_c:
            found_r = True
            if gap_start_r >= 0 and (gap_start_r - x) >= gap_min_px:
                x_max = x + 1
                break
            gap_start_r = -1
        else:
            if found_r and gap_start_r < 0:
                gap_start_r = x

    # Add padding
    x_min = max(0, x_min - padding)
    y_min = max(0, y_min - padding)
    x_max = min(w, x_max + padding)
    y_max = min(h, y_max + padding)

    if (x_max - x_min) < 20 or (y_max - y_min) < 15:
        return img

    return img.crop((x_min, y_min, x_max, y_max))


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
