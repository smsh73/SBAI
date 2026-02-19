"""P&ID 도면 페이지 VLM 분석 서비스

Claude Vision을 사용하여 P&ID 2-3페이지(pump room 도면)에서
valve, pipe 심볼을 식별하고 라인스펙 태그를 추출합니다.
1페이지 레전드 심볼 라이브러리를 참조로 사용합니다.
"""
import anthropic
import base64
import fitz  # PyMuPDF
import json
import logging
import re
import time
from pathlib import Path

from app.core.config import ANTHROPIC_API_KEY
from app.services.symbol_db_service import get_symbol_reference_text

logger = logging.getLogger(__name__)

# 라인스펙 전체 패턴: 10"-CSW-9103-CS3-40#150-NI
LINE_SPEC_FULL = re.compile(
    r'(\d+)"?\s*[-–]\s*'           # SIZE (inches)
    r'([A-Z]{2,4})\s*[-–]\s*'      # SYSTEM CODE (CSW, SSW, CFW, FW)
    r'(\d{4})\s*[-–]\s*'           # LINE NUMBER
    r'(CS\d|SS\d|AL\d)\s*[-–]?\s*' # PIPING CLASS
    r'(\d+|STD|XS)\s*'             # SCHEDULE
    r'(?:[#]\s*(\d+))?\s*'         # PRESSURE RATING (#150)
    r'[-–]?\s*([A-Z]{1,3})?'       # MATERIAL CODE (NI, etc.)
)

# 시스템 코드별 유체 매핑
SYSTEM_FLUID_MAP = {
    "CSW": "SW",   # Cooling Sea Water
    "SSW": "SW",   # Spray Sea Water
    "CFW": "CFW",  # Cooling Fresh Water
    "FW": "FW",    # Fresh Water
}

# ──────────────────────────────────────────────
# VLM 프롬프트
# ──────────────────────────────────────────────
PID_PAGE_ANALYSIS_PROMPT = """You are an expert P&ID (Piping and Instrumentation Diagram) engineer.
You are analyzing page {page_num} of a P&ID drawing for a ship's pump room piping system.

## REFERENCE SYMBOL LIBRARY (from the legend page):
{symbol_reference}

## YOUR TASK:
Carefully analyze this P&ID drawing page and extract ALL of the following:

### 1. LINE SPECIFICATION TAGS
Find EVERY pipe line specification tag visible on the drawing. They follow the format:
SIZE"-SYSTEM_CODE-LINE_NUMBER-PIPING_CLASS-SCHEDULE#PRESSURE_RATING-MATERIAL_CODE

Examples:
- 10"-CSW-9103-CS3-40#150-NI
- 12"-CSW-9112-CS3-STD#150-NI
- 8"-SSW-9201-CS3-40#150-NI
- 6"-CFW-8101-CS2-STD#150-NI

Parse each into components:
- size: pipe diameter in inches (e.g., "10")
- system_code: "CSW" (Cooling Sea Water), "SSW" (Spray Sea Water), "CFW" (Cooling Fresh Water), "FW" (Fresh Water)
- line_number: 4-digit number (e.g., "9103")
- tag: system_code + line_number (e.g., "CSW9103")
- piping_class: "CS3", "CS2", "SS2", etc.
- schedule: "40", "STD", "80", "XS", etc.
- pressure_rating: "150" (from #150)
- material_code: "NI" or other code

### 2. ALL VALVES
Identify EVERY valve on the drawing with:
- tag: the valve tag number (e.g., CSW9112, FCV1234, TCV5678)
- valve_type: from the symbol library (BUTTERFLY, GATE, GLOBE, CHECK, BALL, PLUG, NEEDLE, CONTROL)
- valve_subtype: more specific type (e.g., "BUTTERFLY VALVE", "GATE VALVE (OPEN)", "CHECK VALVE")
- actuator: type of actuator if visible (MANUAL, DIAPHRAGM, PISTON, MOTOR, HYDRAULIC, NONE)
- size: valve size in inches
- associated line_spec: the full line spec string this valve is on
- description: brief description of the valve's function

### 3. PIPE SYMBOLS AND FITTINGS
Identify piping symbols like:
- Strainers, screens, vents, drains
- Expansion joints, sounding caps
- Tees, reducers, elbows
- Flanges
- Equipment connections

### 4. EQUIPMENT
List major equipment visible (pumps, heat exchangers, tanks, sea chests, etc.)

Return ONLY valid JSON:
{{
  "page": {page_num},
  "line_specs": [
    {{
      "full_spec": "10\\"-CSW-9103-CS3-40#150-NI",
      "size": "10",
      "system_code": "CSW",
      "line_number": "9103",
      "tag": "CSW9103",
      "piping_class": "CS3",
      "schedule": "40",
      "pressure_rating": "150",
      "material_code": "NI",
      "fluid": "SW"
    }}
  ],
  "valves": [
    {{
      "tag": "CSW9112",
      "valve_type": "BUTTERFLY",
      "valve_subtype": "BUTTERFLY VALVE",
      "actuator": "MANUAL",
      "size": "12",
      "line_spec": "12\\"-CSW-9112-CS3-STD#150-NI",
      "piping_class": "CS3",
      "schedule": "STD",
      "pressure_rating": "150",
      "material_code": "NI",
      "fluid": "SW",
      "description": "Main CSW pump suction valve"
    }}
  ],
  "symbols_found": [
    {{
      "category": "PIPING",
      "symbol_description": "TEMPORARY STRAINER",
      "tag": "",
      "associated_line": "CSW9103",
      "size": "10"
    }}
  ],
  "equipment": [
    {{
      "name": "NO.2 FWD CSW PUMP",
      "type": "pump",
      "connections": ["CSW9103", "CSW9105"]
    }}
  ],
  "confidence": 0.90
}}

CRITICAL RULES:
1. Extract EVERY line spec tag visible on the drawing - do not miss any
2. The tag is formed by concatenating system_code + line_number (e.g., CSW + 9103 = CSW9103)
3. Identify valve types by matching to the REFERENCE SYMBOL LIBRARY provided above
4. Read ALL text annotations, especially those near valves and pipe lines
5. Return ONLY valid JSON, no markdown"""


def _encode_image(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def _call_vlm(image_path: str, prompt: str, max_tokens: int = 8192) -> str:
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not configured")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    img_data = _encode_image(image_path)

    content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": img_data,
            },
        },
        {"type": "text", "text": prompt},
    ]

    resp = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": content}],
    )
    return resp.content[0].text


def _parse_json_response(text: str) -> dict:
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


def _render_pid_page_for_vlm(pdf_path: str, page_idx: int,
                              output_dir: str, max_px: int = 6000) -> str:
    """P&ID 페이지를 VLM 분석용으로 고해상도 렌더링."""
    doc = fitz.open(pdf_path)
    page = doc[page_idx]
    pw, ph = page.rect.width, page.rect.height

    max_dim = max(pw, ph)
    dpi = min(250, int(max_px / max_dim * 72))
    dpi = max(dpi, 150)

    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat)

    img_path = str(Path(output_dir) / f"pid_vlm_page_{page_idx + 1}.png")
    pix.save(img_path)
    logger.info(f"P&ID page {page_idx + 1} rendered: {pix.width}x{pix.height}px at {dpi}dpi")

    pix = None
    doc.close()
    return img_path


def _parse_line_spec(full_spec: str) -> dict:
    """라인스펙 문자열을 구성요소로 파싱."""
    m = LINE_SPEC_FULL.search(full_spec)
    if m:
        system_code = m.group(2)
        line_number = m.group(3)
        return {
            "full_spec": full_spec.strip(),
            "size": m.group(1),
            "system_code": system_code,
            "line_number": line_number,
            "tag": f"{system_code}{line_number}",
            "piping_class": m.group(4),
            "schedule": m.group(5),
            "pressure_rating": m.group(6) or "150",
            "material_code": m.group(7) or "",
            "fluid": SYSTEM_FLUID_MAP.get(system_code, "SW"),
        }
    return {
        "full_spec": full_spec.strip(),
        "size": "", "system_code": "", "line_number": "",
        "tag": "", "piping_class": "", "schedule": "",
        "pressure_rating": "", "material_code": "",
        "fluid": "",
    }


def _extract_line_specs_from_text(pdf_path: str, page_idx: int) -> list[dict]:
    """PDF 페이지 텍스트에서 라인스펙 추출 (regex 기반 보조)."""
    doc = fitz.open(pdf_path)
    page = doc[page_idx]
    text = page.get_text("text")
    doc.close()

    results = []
    seen_specs = set()
    for m in LINE_SPEC_FULL.finditer(text):
        spec = m.group(0).strip()
        if spec in seen_specs:
            continue
        seen_specs.add(spec)
        parsed = _parse_line_spec(spec)
        parsed["source"] = "text"
        results.append(parsed)

    return results


def _analyze_single_pid_page(pdf_path: str, page_idx: int,
                              output_dir: str, symbol_ref_text: str) -> dict:
    """단일 P&ID 페이지 VLM 분석."""
    page_num = page_idx + 1

    # 1. 렌더링
    img_path = _render_pid_page_for_vlm(pdf_path, page_idx, output_dir)

    # 2. VLM 분석
    prompt = PID_PAGE_ANALYSIS_PROMPT.format(
        page_num=page_num,
        symbol_reference=symbol_ref_text,
    )

    try:
        resp_text = _call_vlm(img_path, prompt, max_tokens=8192)
        vlm_data = _parse_json_response(resp_text)
        if not vlm_data:
            logger.warning(f"P&ID page {page_num}: VLM returned empty data")
            vlm_data = {"page": page_num}
        vlm_data["vlm_ok"] = True
    except Exception as e:
        logger.error(f"P&ID page {page_num} VLM analysis failed: {e}")
        vlm_data = {"page": page_num, "vlm_ok": False, "error": str(e)}

    vlm_data["page"] = page_num

    # 3. 텍스트 추출로 보완
    text_specs = _extract_line_specs_from_text(pdf_path, page_idx)
    vlm_specs = vlm_data.get("line_specs", [])

    # VLM line_specs 파싱 보정
    for spec in vlm_specs:
        full = spec.get("full_spec", "")
        if full and not spec.get("tag"):
            parsed = _parse_line_spec(full)
            spec.update({k: v for k, v in parsed.items() if v and not spec.get(k)})
        spec["source"] = "vlm"

    # 텍스트에서 찾은 것 중 VLM에 없는 것 추가
    vlm_tags = {s.get("tag", "") for s in vlm_specs}
    for ts in text_specs:
        if ts.get("tag") and ts["tag"] not in vlm_tags:
            vlm_specs.append(ts)
            vlm_tags.add(ts["tag"])

    vlm_data["line_specs"] = vlm_specs

    # 4. 밸브 후처리: tag 생성 보정
    for valve in vlm_data.get("valves", []):
        tag = valve.get("tag", "")
        if not tag and valve.get("line_spec"):
            parsed = _parse_line_spec(valve["line_spec"])
            valve["tag"] = parsed.get("tag", "")
        # fluid 보정
        if not valve.get("fluid") and tag:
            for prefix, fluid in SYSTEM_FLUID_MAP.items():
                if tag.startswith(prefix):
                    valve["fluid"] = fluid
                    break

    return vlm_data


def analyze_pid_pages(pdf_path: str, output_dir: str,
                      symbols: list[dict],
                      pages: list[int] | None = None) -> dict:
    """P&ID PDF의 지정 페이지들을 VLM으로 분석.

    Args:
        pdf_path: P&ID PDF 경로
        output_dir: 출력 디렉토리
        symbols: 레전드에서 추출한 심볼 리스트
        pages: 분석할 페이지 인덱스 (0-based). None이면 1,2 (2-3페이지)

    Returns:
        통합 분석 결과 dict
    """
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    doc.close()

    if pages is None:
        # 기본값: 2-3페이지 (0-indexed: 1, 2)
        pages = [i for i in [1, 2] if i < total_pages]

    if not pages:
        logger.warning("No P&ID pages to analyze")
        return {"pages_analyzed": [], "line_specs": [], "valves": [], "symbols_found": []}

    symbol_ref_text = get_symbol_reference_text(symbols) if symbols else ""

    all_line_specs = []
    all_valves = []
    all_symbols = []
    all_equipment = []
    page_results = []
    seen_tags = set()
    seen_valve_tags = set()

    logger.info(f"Starting P&ID VLM analysis: pages {[p+1 for p in pages]}")

    for page_idx in pages:
        page_start = time.time()

        page_result = _analyze_single_pid_page(
            pdf_path, page_idx, output_dir, symbol_ref_text)
        page_results.append(page_result)

        # 라인스펙 병합 (중복 제거)
        for spec in page_result.get("line_specs", []):
            tag = spec.get("tag", "")
            if tag and tag not in seen_tags:
                seen_tags.add(tag)
                spec["sheet"] = page_idx + 1
                all_line_specs.append(spec)

        # 밸브 병합 (중복 제거)
        for valve in page_result.get("valves", []):
            vtag = valve.get("tag", "")
            if vtag and vtag not in seen_valve_tags:
                seen_valve_tags.add(vtag)
                valve["sheet"] = page_idx + 1
                all_valves.append(valve)

        # 심볼 병합
        for sym in page_result.get("symbols_found", []):
            sym["sheet"] = page_idx + 1
            all_symbols.append(sym)

        # 장비 병합
        for eq in page_result.get("equipment", []):
            eq["sheet"] = page_idx + 1
            all_equipment.append(eq)

        elapsed = time.time() - page_start
        logger.info(f"  Page {page_idx + 1}: {len(page_result.get('line_specs', []))} line specs, "
                     f"{len(page_result.get('valves', []))} valves ({elapsed:.1f}s)")

        # Rate limiting
        if page_idx != pages[-1]:
            time.sleep(0.5)

    result = {
        "pages_analyzed": [p + 1 for p in pages],
        "line_specs": all_line_specs,
        "valves": all_valves,
        "symbols_found": all_symbols,
        "equipment": all_equipment,
        "page_details": page_results,
    }

    logger.info(f"P&ID VLM analysis complete: {len(all_line_specs)} line specs, "
                f"{len(all_valves)} valves, {len(all_symbols)} symbols")

    return result


def merge_regex_and_vlm(regex_valves: list[dict], vlm_result: dict) -> list[dict]:
    """regex 기반 밸브 추출과 VLM 결과를 병합.

    VLM 결과가 우선이며, regex에서만 발견된 태그를 보완 추가합니다.
    """
    vlm_valves = vlm_result.get("valves", [])
    vlm_tags = {v.get("tag", "") for v in vlm_valves}

    enhanced = []

    # VLM 밸브가 기본
    for vv in vlm_valves:
        vv["source"] = "vlm"
        enhanced.append(vv)

    # regex에서만 발견된 밸브 추가
    for rv in regex_valves:
        tag = rv.get("tag", "")
        if tag and tag not in vlm_tags:
            rv["source"] = "regex"
            # VLM line_specs에서 매칭되는 라인스펙 찾기
            for ls in vlm_result.get("line_specs", []):
                ls_tag = ls.get("tag", "")
                if ls_tag and tag.startswith(ls_tag[:3]) and tag[3:] == ls_tag[3:]:
                    rv["line_spec"] = ls.get("full_spec", "")
                    rv["piping_class"] = ls.get("piping_class", rv.get("piping_class", ""))
                    rv["schedule"] = ls.get("schedule", rv.get("schedule", ""))
                    rv["pressure_rating"] = ls.get("pressure_rating", "")
                    rv["material_code"] = ls.get("material_code", "")
                    break
            enhanced.append(rv)

    # VLM과 regex 양쪽에 있는 밸브: VLM 데이터에 regex 정보 보완
    regex_map = {rv["tag"]: rv for rv in regex_valves if rv.get("tag")}
    for ev in enhanced:
        if ev.get("source") == "vlm":
            tag = ev.get("tag", "")
            if tag in regex_map:
                ev["source"] = "both"
                rv = regex_map[tag]
                # VLM에 없는 필드만 regex에서 보완
                if not ev.get("location"):
                    ev["location"] = rv.get("location", "")
                if not ev.get("fluid"):
                    ev["fluid"] = rv.get("fluid", "")

    return sorted(enhanced, key=lambda v: v.get("tag", ""))
