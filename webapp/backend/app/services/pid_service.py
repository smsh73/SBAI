"""P&ID PDF에서 밸브 추출 서비스"""
import fitz  # PyMuPDF
import re
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 밸브 태그 패턴
VALVE_TAG_PATTERN = re.compile(
    r'(CSW|SSW|CFW|FW)\d{4}[A-Z]?'  # Manual valves
    r'|'
    r'(FCV|TCV|XV|LCV|PCV)\d{4}[A-Z]?'  # Control valves
)

# 라인 스펙 패턴: SIZE"-SERVICE-LINE#-CLASS-SCHEDULE 등
LINE_SPEC_PATTERN = re.compile(
    r'(\d+)"?\s*-\s*([A-Z]+)\s*-\s*(\w+)\s*-\s*(CS\d|SS\d|AL\d)\s*(?:-\s*(STD|40|80|XS|160|10|20))?'
)

# 밸브 타입 매핑
VALVE_TYPE_KEYWORDS = {
    "BFV": "BUTTERFLY",
    "BUTTERFLY": "BUTTERFLY",
    "GATE": "GATE",
    "GLOBE": "GLOBE",
    "CHECK": "CHECK",
    "BALL": "BALL",
    "PLUG": "PLUG",
    "NEEDLE": "NEEDLE",
    "FCV": "CONTROL",
    "TCV": "CONTROL",
    "XV": "CONTROL",
    "LCV": "CONTROL",
    "PCV": "CONTROL",
}


def extract_valves(pdf_path: str) -> list[dict]:
    """P&ID PDF에서 밸브 목록 추출"""
    doc = fitz.open(pdf_path)
    valves = []
    seen_tags = set()

    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text("text")
        blocks = page.get_text("blocks")

        # 밸브 태그 찾기
        for match in VALVE_TAG_PATTERN.finditer(text):
            tag = match.group()
            if tag in seen_tags:
                continue
            seen_tags.add(tag)

            # 태그 주변 텍스트에서 정보 추출
            context = _get_context(text, match.start(), window=500)

            valve = {
                "tag": tag,
                "valve_type": _detect_valve_type(tag, context),
                "valve_subtype": "",
                "line_spec": "",
                "size": "",
                "piping_class": "CS3",
                "schedule": "STD",
                "pressure_rating": "150",
                "material_code": "",
                "location": _detect_location(tag),
                "description": "",
                "fluid": _detect_fluid(tag),
                "sheet": page_num + 1,
            }

            # 라인 스펙 파싱
            spec_match = LINE_SPEC_PATTERN.search(context)
            if spec_match:
                valve["size"] = spec_match.group(1)
                valve["line_spec"] = spec_match.group(0)
                valve["piping_class"] = spec_match.group(4) or "CS3"
                valve["schedule"] = spec_match.group(5) or "STD"

            # 밸브 타입 상세
            vtype = valve["valve_type"]
            if vtype == "BUTTERFLY":
                valve["valve_subtype"] = "BUTTERFLY VALVE"
                valve["description"] = f"{valve['size']}\" BUTTERFLY VALVE"
            elif vtype == "GATE":
                valve["valve_subtype"] = "GATE VALVE"
                valve["description"] = f"{valve['size']}\" GATE VALVE"
            elif vtype == "CHECK":
                valve["valve_subtype"] = "CHECK VALVE"
                valve["description"] = f"{valve['size']}\" CHECK VALVE"
            elif vtype == "CONTROL":
                valve["valve_subtype"] = _detect_control_subtype(tag, context)
                valve["description"] = f"{valve['size']}\" CONTROL VALVE ({valve['valve_subtype']})"
            else:
                valve["valve_subtype"] = f"{vtype} VALVE"
                valve["description"] = f"{valve['size']}\" {vtype} VALVE"

            valves.append(valve)

    doc.close()
    logger.info(f"Extracted {len(valves)} valves from {pdf_path}")
    return valves


def _get_context(text: str, pos: int, window: int = 500) -> str:
    start = max(0, pos - window)
    end = min(len(text), pos + window)
    return text[start:end]


def _detect_valve_type(tag: str, context: str) -> str:
    prefix = tag[:3] if len(tag) >= 3 else tag[:2]
    if prefix in ("FCV", "TCV", "LCV", "PCV"):
        return "CONTROL"
    if prefix == "XV":
        return "CONTROL"

    ctx_upper = context.upper()
    for kw, vtype in VALVE_TYPE_KEYWORDS.items():
        if kw in ctx_upper:
            return vtype

    return "BUTTERFLY"  # default


def _detect_fluid(tag: str) -> str:
    if tag.startswith("SSW"):
        return "SW"
    if tag.startswith("CSW"):
        return "SW"
    if tag.startswith("CFW"):
        return "CFW"
    if tag.startswith("FW"):
        return "FW"
    if tag.startswith("FCV") or tag.startswith("TCV") or tag.startswith("XV"):
        return "SW"
    return "SW"


def _detect_location(tag: str) -> str:
    if tag.startswith("SSW"):
        return "SPRAY SEA WATER SYSTEM"
    if tag.startswith("CSW"):
        return "COOLING SEA WATER SYSTEM"
    if tag.startswith("CFW"):
        return "COOLING FRESH WATER SYSTEM"
    if tag.startswith("FW"):
        return "FRESH WATER SYSTEM"
    return "GENERAL"


def _detect_control_subtype(tag: str, context: str) -> str:
    if tag.startswith("FCV"):
        return "FLOW CONTROL VALVE"
    if tag.startswith("TCV"):
        return "TEMPERATURE CONTROL VALVE"
    if tag.startswith("XV"):
        return "SHUTOFF VALVE"
    if tag.startswith("LCV"):
        return "LEVEL CONTROL VALVE"
    if tag.startswith("PCV"):
        return "PRESSURE CONTROL VALVE"
    return "CONTROL VALVE"


def render_pid_pages(pdf_path: str, output_dir: str, dpi: int = 200) -> list[str]:
    """P&ID PDF 페이지를 이미지로 렌더링"""
    doc = fitz.open(pdf_path)
    results = []
    for i in range(min(len(doc), 10)):  # 최대 10페이지
        page = doc[i]
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        out_path = Path(output_dir) / f"pid_page{i+1}.png"
        pix.save(str(out_path))
        results.append(str(out_path))
    doc.close()
    return results
