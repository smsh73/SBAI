"""VLM 기반 PIPE BOM 정밀 추출 서비스

Claude Vision을 사용하여 파이핑 아이소메트릭 도면에서
파이프, 밸브, 피팅, 치수, BOM 테이블 데이터를 정밀 추출.

Burckhardt Compression / Kuraray Singapore 형식 특화.
"""
import fitz
import anthropic
import base64
import json
import logging
import re
import time
from pathlib import Path
from app.core.config import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

# BOM 테이블 크롭 영역 (페이지 우측)
TABLE_CROP_X_RATIO = 0.70  # 페이지 폭의 70%~100% 영역이 BOM 테이블

# ──────────────────────────────────────────────
# VLM 프롬프트 (도면 분석)
# ──────────────────────────────────────────────
DRAWING_ANALYSIS_PROMPT = """You are an expert marine/plant piping engineer. Analyze this piping isometric drawing (page {page_num}).

The LEFT side shows the isometric pipe routing with:
- Pipe piece IDs in RED text (format: PGxxx-n, e.g. PG119-1, PG101-3)
- Weld points marked as small circles or triangles (numbered W1, W2... for shop welds, FFW1, FFW2... for field-fit welds)
- Dimension annotations in mm between weld points
- Component symbols for valves, elbows, tees, reducers, flanges
- Items marked "(Loose)" are shipped separately

The RIGHT side has the BOM table and title block (analyzed separately - you can skip the table).

Return a JSON object with this EXACT structure:
{{
  "page": {page_num},
  "drawing_number": "number from title block bottom-right (format: X-125.629.XXX)",
  "pipe_group": "main pipe group from drawing (e.g. PG101, PG119, PG120)",
  "line_no": "LINE NO. from title block (e.g. 101, 119, 120)",
  "pipe_no": "PIPE NO. from title block (e.g. 6_S1-1, G_D4-3)",
  "line_description": "title from title block (e.g. SUCTION LINE 1ST STAGE (INLET))",
  "pipe_pieces": [
    {{"id": "PG101-1", "size": "6\\"", "schedule": "Sch80S", "material": "SS304"}}
  ],
  "components": [
    {{
      "type": "valve|fitting|flange|reducer|support|instrument",
      "subtype": "gate|globe|ball|check|butterfly|needle|non_return|elbow_90|elbow_45|elbow_90_lr|tee|reducing_tee|reducer_con|reducer_ecc|wn_flange|blind_flange|orifice_flange|sockolet|weldolet|coupling|cap|clamp|support",
      "size": "size in inches",
      "description": "full description",
      "tag": "tag number if visible",
      "quantity": 1
    }}
  ],
  "weld_points": [
    {{"id": "W1", "type": "shop_weld"}},
    {{"id": "FFW1", "type": "field_fit_weld"}}
  ],
  "dimensions_mm": [
    {{"from_point": "W1", "to_point": "W2", "length_mm": 500, "direction": "horizontal|vertical|angled"}}
  ],
  "total_weld_count": 16,
  "shop_weld_count": 14,
  "field_weld_count": 2,
  "has_loose_parts": false,
  "notes": "revision notes visible on drawing (Korean text OK)",
  "confidence": 0.95
}}

RULES:
1. Read EVERY red pipe piece ID (PGxxx-n format) from the drawing
2. Count ALL weld symbols precisely: W# = shop weld (circle), FFW# = field fit weld (triangle)
3. Read ALL dimension numbers in mm between weld points
4. Identify component symbols: elbows (curved), tees (T-junction), reducers (tapered), flanges (thick bar), valves (special symbols)
5. Check for "(Loose)" annotations on any components
6. Return ONLY valid JSON"""

# ──────────────────────────────────────────────
# VLM 프롬프트 (BOM 테이블 정밀 분석)
# ──────────────────────────────────────────────
TABLE_ANALYSIS_PROMPT = """You are an expert at reading Burckhardt Compression piping BOM tables.

This is the BOM TABLE AREA from page {page_num} of a piping isometric drawing.

The table has THREE distinct sections. Read them ALL separately:

## SECTION 1: BOM ITEMS TABLE (top section, labeled "A")
Column headers (left to right):
  N | QUANT | FIT DESCRIPTION / STANDARD/CODE | DIMENSION / MATERIAL | WEIGHT

Each BOM row has a LETTER CODE (A, B, C, D, E, F, G, H, etc.) in the description.
Common letter codes:
- A = Main PIPE (SMLS = seamless, e.g. "A PIPE SMLS ASME B36.19M")
- B = Branch/secondary PIPE
- C = TEE or REDUCING TEE (ASME B16.9)
- D = REDUCER (CONCENTRIC or ECCENTRIC, ASME B16.9)
- E = SOCKOLET or WELDOLET (ASME B16.11)
- F = WN FLANGE RF (Welding Neck Raised Face, ASME B16.5)
- G, H = Additional flanges or fittings
- M, N = WN FLANGE, BLIND FLANGE, ORIFICE FLANGE (ASME B16.5)
- O, P = SPIRAL WOUND GASKET (ASME B16.20)
- Q, R = STUD BOLT (ASME B18.2.1)
- S = CLAMP (pipe support)
- T = NUT (ASME B18.2.2)

## SECTION 2: CUT LENGTHS TABLE (middle section, labeled "B")
Header: LENGTH | CUT / NO.
Rows format: "XXX MM" with cut number "<1>", "<2>", etc.
Example: "736 MM <1>", "94 MM <2>", "729 MM <3>"
These are individual pipe piece cut lengths for fabrication.

## SECTION 3: TITLE BLOCK (bottom section, labeled "E")
Contains: Company (KURARAY SINGAPORE 01), Project (SLP250-4D_1),
Line description (e.g. DISCHARGE LINE 4TH STAGE),
LINE NO., PIPE NO., Drawing number (1-125.629.XXX), Revision

Return this EXACT JSON structure:
{{
  "page": {page_num},
  "table_headers": ["N", "QUANT", "FIT DESCRIPTION/STANDARD", "DIMENSION/MATERIAL", "WEIGHT"],
  "bom_items": [
    {{
      "letter_code": "A",
      "quantity": "9.5 M",
      "size_inches": "6\\"",
      "description": "PIPE SMLS ASME B36.19M",
      "material_spec": "6\\" Sch-d 80S A312 TP304/304L",
      "weight_kg": 491,
      "remarks": ""
    }}
  ],
  "cut_lengths": [
    {{"cut_no": 1, "length_mm": 736}},
    {{"cut_no": 2, "length_mm": 94}}
  ],
  "drawing_info": {{
    "drawing_number": "1-125.629.XXX",
    "revision": "E",
    "date": "15-01-2025",
    "scale": "",
    "project": "KURARAY SINGAPORE 01 SLP250-4D_1",
    "line_description": "DISCHARGE LINE 4TH STAGE (OUTLET)",
    "line_no": "120",
    "pipe_no": "G_D4-3"
  }},
  "bom_totals": {{
    "total_weight_kg": 1295,
    "total_pipe_length_m": 9.5
  }}
}}

CRITICAL RULES:
1. BOM items and CUT LENGTHS are SEPARATE sections - do NOT mix them
2. Read the letter code (A, B, C...) from the start of each description
3. Read quantity carefully: pipe quantities are in meters (e.g. "9.5 M", "0.2 M"), other items are integers
4. Size is in inches (e.g. 6", 4", 3/4")
5. Material spec includes pipe schedule, ASTM grade, and material (e.g. "6\\" Sch-d 80S A312 TP304/304L")
6. Weight is in kg (rightmost column)
7. Cut lengths are in MM with angle bracket numbers: "736 MM <1>"
8. Read the COMPLETE drawing number from title block (format: X-125.629.XXX)
9. Read LINE NO. and PIPE NO. from title block
10. Return ONLY valid JSON, no markdown"""

# ──────────────────────────────────────────────
# Page 1 전용 프롬프트 (다른 포맷)
# ──────────────────────────────────────────────
TABLE_ANALYSIS_PROMPT_PAGE1 = """You are reading a piping BOM table from page 1 of an isometric drawing package.

This page has a DIFFERENT format from other pages. It uses a simple numbered table:

Columns: ITEM | QTY | SIZE | DESCRIPTION | MATERIAL SPEC | LENGTH | WEIGHT | UNIT WT | REMARKS

Items are numbered (1, 2, 3...) and include:
- PIPE (with size and schedule)
- ELBOW 90 LR (Long Radius 90-degree elbow)
- FLANGE WN RF (Welding Neck Raised Face) with pressure class
- GASKET
- BOLT & NUT
- SUPPORT TYPE S-1, S-2 etc.
- PAINTING
- SUB TOTAL and GRAND TOTAL rows

Return this JSON:
{{
  "page": 1,
  "table_headers": ["ITEM", "QTY", "SIZE", "DESCRIPTION", "MATERIAL SPEC", "LENGTH", "WEIGHT", "UNIT WT", "REMARKS"],
  "bom_items": [
    {{
      "item_no": "1",
      "quantity": 1,
      "size_inches": "6\\"",
      "description": "PIPE SMLS SCH 40",
      "material_spec": "A53 GR.B",
      "length_mm": 6096,
      "weight_kg": 0,
      "remarks": ""
    }}
  ],
  "cut_lengths": [],
  "drawing_info": {{
    "drawing_number": "0-125.629.098",
    "revision": "E",
    "date": "",
    "scale": "",
    "project": "SUCTION LINE 1ST STAGE (INLET)",
    "line_description": "SUCTION LINE 1ST STAGE (INLET)",
    "line_no": "101",
    "pipe_no": "6_S1-1"
  }},
  "bom_totals": {{
    "total_weight_kg": 0,
    "total_pipe_length_m": 0
  }}
}}

RULES:
1. Read EVERY row including SUB TOTAL and GRAND TOTAL
2. Copy material specifications exactly
3. Return ONLY valid JSON"""


def _encode_image(image_path: str) -> str:
    """이미지를 base64로 인코딩"""
    with open(image_path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def _call_vlm(images: list[tuple[str, str]], prompt: str, max_tokens: int = 4096) -> str:
    """Claude VLM API 호출"""
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not configured")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    content = []
    for img_path, media_type in images:
        img_data = _encode_image(img_path)
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": img_data,
            },
        })
    content.append({"type": "text", "text": prompt})

    resp = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": content}],
    )
    return resp.content[0].text


def _parse_json_response(text: str) -> dict:
    """VLM 응답에서 JSON 추출 및 파싱"""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        logger.error(f"Failed to parse VLM JSON response: {text[:300]}")
        return {}


def _postprocess_bom_items(items: list[dict]) -> list[dict]:
    """BOM 아이템 후처리: 정리, 검증, 정규화"""
    cleaned = []
    for item in items:
        if not isinstance(item, dict):
            continue

        # letter_code 또는 item_no 정규화
        letter = item.get("letter_code", "") or item.get("item_no", "")
        desc = item.get("description", "")

        # description에서 letter_code 분리 (e.g. "A PIPE SMLS" -> code=A, desc=PIPE SMLS)
        if not letter and desc:
            m = re.match(r'^([A-Z])\s+(.+)', desc)
            if m:
                letter = m.group(1)
                desc = m.group(2)

        # 빈 행 또는 헤더 행 건너뛰기
        if not desc and not letter:
            continue
        # "LENGTH" 헤더 행 건너뛰기 (cut lengths 섹션 시작)
        if letter.upper() in ("LENGTH", "CUT"):
            continue
        # cut length 행 감지 (e.g. "736 MM <1>") -> 건너뛰기
        if re.match(r'^\d+\s*MM', desc) or re.match(r'^\d+\s*MM', str(letter)):
            continue

        # weight_kg 정규화
        weight = item.get("weight_kg", 0)
        if isinstance(weight, str):
            w_match = re.search(r'[\d.]+', weight)
            weight = float(w_match.group()) if w_match else 0

        # quantity 정규화
        qty = item.get("quantity", "")
        if isinstance(qty, (int, float)):
            qty = str(qty) if qty else ""

        cleaned.append({
            "letter_code": letter.strip(),
            "quantity": str(qty).strip(),
            "size_inches": str(item.get("size_inches", "")).strip(),
            "description": desc.strip(),
            "material_spec": str(item.get("material_spec", "")).strip(),
            "weight_kg": float(weight) if weight else 0,
            "remarks": str(item.get("remarks", "")).strip(),
        })
    return cleaned


def _postprocess_cut_lengths(cuts: list, bom_items: list[dict]) -> list[dict]:
    """Cut length 후처리 및 BOM에서 섞인 cut length 분리"""
    cleaned_cuts = []

    # 명시적 cut_lengths 배열 처리
    for cut in (cuts or []):
        if isinstance(cut, dict):
            cut_no = cut.get("cut_no", 0)
            length = cut.get("length_mm", 0)
            if isinstance(length, str):
                m = re.search(r'[\d.]+', length)
                length = float(m.group()) if m else 0
            elif length is None:
                length = 0
            if length and float(length) > 0:
                cn = int(cut_no) if cut_no and str(cut_no).isdigit() else len(cleaned_cuts) + 1
                cleaned_cuts.append({"cut_no": cn, "length_mm": float(length)})

    # BOM 아이템에서 잘못 섞인 cut length 추출
    remaining_bom = []
    for item in bom_items:
        desc = item.get("description", "")
        letter = item.get("letter_code", "") or item.get("item_no", "")

        # "332 MM <6>" 또는 "736 MM" 패턴 감지
        cut_match = re.match(r'^(\d+)\s*MM\s*(?:<(\d+)>)?', desc)
        letter_cut_match = re.match(r'^(\d+)\s*MM', str(letter))

        if cut_match:
            length = float(cut_match.group(1))
            cut_no = int(cut_match.group(2)) if cut_match.group(2) else len(cleaned_cuts) + 1
            cleaned_cuts.append({"cut_no": cut_no, "length_mm": length})
        elif letter_cut_match:
            length = float(letter_cut_match.group(1))
            cleaned_cuts.append({"cut_no": len(cleaned_cuts) + 1, "length_mm": length})
        else:
            remaining_bom.append(item)

    # cut_no로 정렬
    cleaned_cuts.sort(key=lambda c: c["cut_no"])
    return cleaned_cuts, remaining_bom


def render_page_for_vlm(doc, page_num: int, output_dir: str, max_px: int = 7500) -> tuple[str, str]:
    """VLM 분석용 페이지 렌더링 (전체 + 테이블 크롭)"""
    page = doc[page_num]
    page_width = page.rect.width
    page_height = page.rect.height

    # DPI 자동 계산: 최대 치수가 max_px 이내
    max_dim_pts = max(page_width, page_height)
    dpi = min(250, int(max_px / max_dim_pts * 72))
    dpi = max(dpi, 120)

    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat)

    full_path = str(Path(output_dir) / f"vlm_page_{page_num + 1:03d}.png")
    pix.save(full_path)
    logger.debug(f"Page {page_num+1}: {pix.width}x{pix.height}px at {dpi}dpi")

    # BOM 테이블 영역 크롭 (우측 30%)
    table_path = str(Path(output_dir) / f"vlm_table_{page_num + 1:03d}.png")
    try:
        table_x0 = page_width * TABLE_CROP_X_RATIO
        clip_rect = fitz.Rect(table_x0, 0, page_width, page_height)
        crop_w = page_width * (1 - TABLE_CROP_X_RATIO)
        crop_h = page_height
        table_dpi = min(300, int(max_px / max(crop_w, crop_h) * 72))
        table_dpi = max(table_dpi, 150)
        table_mat = fitz.Matrix(table_dpi / 72, table_dpi / 72)
        table_pix = page.get_pixmap(matrix=table_mat, clip=clip_rect)
        table_pix.save(table_path)
        logger.debug(f"Table crop page {page_num+1}: {table_pix.width}x{table_pix.height}px at {table_dpi}dpi")
        table_pix = None
    except Exception as e:
        logger.warning(f"Table crop failed for page {page_num + 1}: {e}")
        table_path = None

    pix = None
    return full_path, table_path


def analyze_single_page(full_img: str, table_img: str | None,
                        page_num: int, symbol_ref: str = "") -> dict:
    """단일 BOM 페이지 VLM 분석 (2-pass)"""
    result = {"page": page_num, "vlm_source": "claude-sonnet-4-5"}

    # Pass 1: 전체 페이지 - 도면 분석 (파이프, 용접, 치수, 컴포넌트)
    prompt = DRAWING_ANALYSIS_PROMPT.format(page_num=page_num)
    if symbol_ref:
        prompt += f"\n\nREFERENCE SYMBOLS from P&ID Legend:\n{symbol_ref}"

    try:
        resp_text = _call_vlm([(full_img, "image/png")], prompt, max_tokens=4096)
        drawing_data = _parse_json_response(resp_text)
        if drawing_data:
            result.update(drawing_data)
            result["drawing_analysis_ok"] = True
        else:
            result["drawing_analysis_ok"] = False
            logger.warning(f"Page {page_num}: Drawing analysis returned empty")
    except Exception as e:
        logger.error(f"Page {page_num}: Drawing analysis failed: {e}")
        result["drawing_analysis_ok"] = False
        result["drawing_error"] = str(e)

    # Pass 2: BOM 테이블 정밀 분석 (크롭 이미지, 더 높은 해상도)
    if table_img and Path(table_img).exists():
        # 페이지 1은 다른 포맷
        if page_num == 1:
            table_prompt = TABLE_ANALYSIS_PROMPT_PAGE1
        else:
            table_prompt = TABLE_ANALYSIS_PROMPT.format(page_num=page_num)

        try:
            table_resp = _call_vlm([(table_img, "image/png")], table_prompt, max_tokens=8000)
            table_data = _parse_json_response(table_resp)
            if table_data:
                # BOM 아이템 후처리
                raw_items = table_data.get("bom_items", []) or table_data.get("items", [])
                bom_items = _postprocess_bom_items(raw_items)

                # Cut length 분리 (BOM에서 섞인 것 포함)
                raw_cuts = table_data.get("cut_lengths", [])
                cut_lengths, bom_items = _postprocess_cut_lengths(raw_cuts, bom_items)

                result["bom_table"] = bom_items
                result["cut_lengths"] = cut_lengths

                if table_data.get("drawing_info"):
                    result["drawing_info"] = table_data["drawing_info"]
                if table_data.get("bom_totals"):
                    result["bom_totals"] = table_data["bom_totals"]
                if table_data.get("table_headers"):
                    result["table_headers"] = table_data["table_headers"]
                result["table_analysis_ok"] = True
        except Exception as e:
            logger.error(f"Page {page_num}: Table analysis failed: {e}")
            result["table_analysis_ok"] = False

    # 후처리: 도면 분석에서 가져온 정보로 보완
    _enrich_from_drawing_info(result)

    return result


def _enrich_from_drawing_info(result: dict):
    """drawing_info에서 결과 보완"""
    di = result.get("drawing_info", {})
    if di:
        if not result.get("drawing_number") and di.get("drawing_number"):
            result["drawing_number"] = di["drawing_number"]
        if not result.get("line_no") and di.get("line_no"):
            result["line_no"] = di["line_no"]
        if not result.get("pipe_no") and di.get("pipe_no"):
            result["pipe_no"] = di["pipe_no"]
        if not result.get("line_description") and di.get("line_description"):
            result["line_description"] = di["line_description"]


def _merge_text_and_vlm(text_data: dict, vlm_data: dict) -> dict:
    """텍스트 추출 + VLM 결과 병합 (교차 검증)"""
    merged = dict(vlm_data)

    # 텍스트에서 추출한 파이프 피스가 VLM에 없으면 추가
    text_pieces = set(text_data.get("pipe_pieces", []))
    vlm_pieces = set()
    for pp in vlm_data.get("pipe_pieces", []):
        if isinstance(pp, dict):
            vlm_pieces.add(pp.get("id", ""))
        else:
            vlm_pieces.add(str(pp))

    missing_pieces = text_pieces - vlm_pieces
    if missing_pieces:
        existing = merged.get("pipe_pieces", [])
        for mp in missing_pieces:
            existing.append({"id": mp, "size": "", "schedule": "", "material": "", "source": "text_extraction"})
        merged["pipe_pieces"] = existing

    # 용접 카운트 교차 검증
    text_weld_count = text_data.get("weld_count", 0)
    vlm_weld_count = merged.get("total_weld_count", 0)
    if text_weld_count > 0 and vlm_weld_count > 0:
        merged["weld_count_text"] = text_weld_count
        merged["weld_count_vlm"] = vlm_weld_count
        merged["total_weld_count"] = max(text_weld_count, vlm_weld_count)

    # 치수 데이터 병합
    text_dims = text_data.get("dimensions_mm", [])
    if text_dims and not merged.get("dimensions_mm"):
        merged["dimensions_mm"] = [{"length_mm": d, "source": "text"} for d in text_dims]

    return merged


def process_bom_with_vlm(pdf_path: str, output_dir: str,
                         symbol_ref: str = "",
                         text_extraction_data: list[dict] | None = None,
                         progress_callback=None) -> list[dict]:
    """전체 PIPE BOM PDF를 VLM으로 정밀 분석"""
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    results = []

    vlm_dir = Path(output_dir) / "vlm_analysis"
    vlm_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Starting VLM analysis of {total_pages} BOM pages")
    start_time = time.time()

    for page_idx in range(total_pages):
        page_num = page_idx + 1
        page_start = time.time()

        # 1. VLM용 이미지 렌더링
        full_img, table_img = render_page_for_vlm(doc, page_idx, str(vlm_dir))

        # 2. VLM 분석
        try:
            page_result = analyze_single_page(full_img, table_img, page_num, symbol_ref)
        except Exception as e:
            logger.error(f"Page {page_num} VLM analysis failed: {e}")
            page_result = {"page": page_num, "error": str(e)}

        # 3. 텍스트 추출 결과와 병합 (교차 검증)
        if text_extraction_data and page_idx < len(text_extraction_data):
            page_result = _merge_text_and_vlm(text_extraction_data[page_idx], page_result)

        results.append(page_result)

        elapsed = time.time() - page_start
        logger.info(f"  Page {page_num}/{total_pages} analyzed ({elapsed:.1f}s) "
                     f"draw={page_result.get('drawing_analysis_ok')} "
                     f"table={page_result.get('table_analysis_ok')} "
                     f"bom={len(page_result.get('bom_table', []))} "
                     f"cuts={len(page_result.get('cut_lengths', []))}")

        if progress_callback:
            progress_callback(page_num, total_pages)

        # Rate limiting (Anthropic API)
        if page_num < total_pages:
            time.sleep(0.5)

    doc.close()

    total_elapsed = time.time() - start_time
    logger.info(f"VLM analysis complete: {total_pages} pages in {total_elapsed:.1f}s")

    # 결과 JSON 저장
    json_path = Path(output_dir) / "vlm_bom_data.json"
    with open(json_path, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # 통계 요약
    stats = _compute_extraction_stats(results)
    stats_path = Path(output_dir) / "vlm_extraction_stats.json"
    with open(stats_path, "w") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    logger.info(f"Extraction stats: {json.dumps(stats, indent=2)}")
    return results


def _compute_extraction_stats(results: list[dict]) -> dict:
    """추출 결과 통계 계산"""
    total_pages = len(results)
    pages_with_data = sum(1 for r in results if r.get("pipe_pieces") or r.get("bom_table"))
    total_pipe_pieces = 0
    total_components = 0
    total_weld_points = 0
    total_bom_items = 0
    total_cut_lengths = 0
    total_dimensions = 0
    drawing_ok = 0
    table_ok = 0

    valve_types = {}
    fitting_types = {}
    all_line_nos = set()

    for r in results:
        if r.get("drawing_analysis_ok"):
            drawing_ok += 1
        if r.get("table_analysis_ok"):
            table_ok += 1
        if r.get("line_no"):
            all_line_nos.add(str(r["line_no"]))

        total_pipe_pieces += len(r.get("pipe_pieces", []))
        total_components += len(r.get("components", []))
        for c in r.get("components", []):
            ctype = c.get("type", "unknown")
            subtype = c.get("subtype", "unknown")
            qty = c.get("quantity", 1)
            if ctype == "valve":
                valve_types[subtype] = valve_types.get(subtype, 0) + qty
            elif ctype == "fitting":
                fitting_types[subtype] = fitting_types.get(subtype, 0) + qty

        total_weld_points += len(r.get("weld_points", []))
        total_bom_items += len(r.get("bom_table", []))
        total_cut_lengths += len(r.get("cut_lengths", []))
        total_dimensions += len(r.get("dimensions_mm", []))

    return {
        "total_pages": total_pages,
        "pages_with_data": pages_with_data,
        "drawing_analysis_success": drawing_ok,
        "table_analysis_success": table_ok,
        "total_pipe_pieces": total_pipe_pieces,
        "total_components": total_components,
        "total_weld_points": total_weld_points,
        "total_bom_items": total_bom_items,
        "total_cut_lengths": total_cut_lengths,
        "total_dimensions": total_dimensions,
        "valve_types": valve_types,
        "fitting_types": fitting_types,
        "unique_line_nos": sorted(all_line_nos),
        "analysis_coverage_pct": round(pages_with_data / total_pages * 100, 1) if total_pages else 0,
    }
