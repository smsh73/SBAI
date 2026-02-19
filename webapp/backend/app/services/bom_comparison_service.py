"""BOM Table vs Drawing Component 비교 서비스

VLM 분석으로 추출한 BOM 테이블 아이템과 도면 컴포넌트를 비교하여
수량 일치/불일치를 판정합니다.
"""
import logging
import re
from collections import defaultdict

logger = logging.getLogger(__name__)

# BOM letter code → (component_type, [possible subtypes])
BOM_LETTER_TO_TYPES = {
    "A": ("pipe", ["pipe"]),
    "B": ("pipe", ["pipe"]),
    "C": ("fitting", ["tee", "reducing_tee", "equal_tee"]),
    "D": ("fitting", ["reducer_con", "reducer_ecc", "reducer"]),
    "E": ("fitting", ["sockolet", "weldolet"]),
    "F": ("flange", ["wn_flange"]),
    "G": ("flange", ["wn_flange"]),
    "H": ("flange", ["blind_flange", "wn_flange"]),
    "I": ("flange", ["orifice_flange"]),
    "J": ("fitting", ["elbow_90", "elbow_90_lr", "elbow_45"]),
    "K": ("fitting", ["cap", "coupling"]),
    "L": ("fitting", ["elbow_90", "elbow_90_lr"]),
    "M": ("flange", ["wn_flange"]),
    "N": ("flange", ["blind_flange"]),
}

# 비교 스킵 대상 letter codes (도면 심볼로 표현되지 않는 항목)
SKIP_LETTER_CODES = {"O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z"}

# BOM description 키워드 → component subtype 매핑
DESCRIPTION_TO_SUBTYPE = {
    "PIPE": "pipe",
    "ELBOW 90 LR": "elbow_90_lr",
    "ELBOW 90": "elbow_90",
    "ELBOW 45": "elbow_45",
    "EQUAL TEE": "tee",
    "REDUCING TEE": "reducing_tee",
    "TEE": "tee",
    "REDUCER CON": "reducer_con",
    "REDUCER ECC": "reducer_ecc",
    "REDUCER ECCENTRIC": "reducer_ecc",
    "REDUCER CONCENTRIC": "reducer_con",
    "REDUCER": "reducer_con",
    "WN FLANGE": "wn_flange",
    "FLANGE WN": "wn_flange",
    "BLIND FLANGE": "blind_flange",
    "ORIFICE FLANGE": "orifice_flange",
    "SOCKOLET": "sockolet",
    "WELDOLET": "weldolet",
    "GATE VALVE": "gate",
    "GLOBE VALVE": "globe",
    "BALL VALVE": "ball",
    "CHECK VALVE": "check",
    "NEEDLE VALVE": "needle",
    "NON RETURN": "non_return",
    "BUTTERFLY": "butterfly",
    "CLAMP": "clamp",
    "SUPPORT": "support",
    "CAP": "cap",
    "COUPLING": "coupling",
}

# description 키워드 → component type 매핑
DESCRIPTION_TO_TYPE = {
    "PIPE": "pipe",
    "ELBOW": "fitting",
    "TEE": "fitting",
    "REDUCER": "fitting",
    "SOCKOLET": "fitting",
    "WELDOLET": "fitting",
    "CAP": "fitting",
    "COUPLING": "fitting",
    "FLANGE": "flange",
    "VALVE": "valve",
    "GASKET": "gasket",
    "BOLT": "bolt",
    "NUT": "bolt",
    "STUD": "bolt",
    "CLAMP": "support",
    "SUPPORT": "support",
    "PAINT": "skip",
    "GALVAN": "skip",
}


def _get_component_info_from_bom(item: dict) -> tuple[str, str, bool]:
    """BOM 아이템에서 component type과 subtype을 추론.

    Returns:
        (component_type, subtype, should_skip)
    """
    letter = (item.get("letter_code") or "").strip().upper()
    desc = (item.get("description") or "").strip().upper()

    # letter code가 스킵 대상이면 건너뛰기
    if letter in SKIP_LETTER_CODES:
        return "", "", True

    # description에서 스킵 대상 확인
    for kw in ("GASKET", "BOLT", "NUT", "STUD", "PAINT", "GALVAN"):
        if kw in desc:
            return "", "", True

    # description에서 subtype 매칭 (긴 키워드 우선)
    subtype = ""
    comp_type = ""
    for kw in sorted(DESCRIPTION_TO_SUBTYPE.keys(), key=len, reverse=True):
        if kw in desc:
            subtype = DESCRIPTION_TO_SUBTYPE[kw]
            break

    for kw in sorted(DESCRIPTION_TO_TYPE.keys(), key=len, reverse=True):
        if kw in desc:
            comp_type = DESCRIPTION_TO_TYPE[kw]
            break

    # letter code 기반 폴백
    if not subtype and letter in BOM_LETTER_TO_TYPES:
        comp_type, subtypes = BOM_LETTER_TO_TYPES[letter]
        subtype = subtypes[0] if subtypes else ""

    if not comp_type and letter in BOM_LETTER_TO_TYPES:
        comp_type = BOM_LETTER_TO_TYPES[letter][0]

    if comp_type in ("skip", "gasket", "bolt"):
        return "", "", True

    return comp_type, subtype, False


def _parse_bom_quantity(qty) -> float:
    """BOM quantity를 숫자로 파싱. '2', '9.5 M', '0.2 M' 등 처리."""
    if isinstance(qty, (int, float)):
        return float(qty)
    if not qty:
        return 0
    qty_str = str(qty).strip()
    # "9.5 M" → 9.5 (미터 단위 파이프 길이, 수량 비교에서 제외)
    m = re.search(r'([\d.]+)', qty_str)
    if m:
        return float(m.group(1))
    return 0


def _is_pipe_length_qty(qty) -> bool:
    """파이프 수량이 미터 단위인지 확인 (수량 비교 불가)."""
    if isinstance(qty, str) and "M" in qty.upper():
        return True
    return False


def compare_single_page(page_data: dict) -> dict:
    """단일 페이지의 BOM 테이블 vs 도면 컴포넌트 비교.

    Args:
        page_data: VLM 분석 결과 (bom_table + components 포함)

    Returns:
        비교 결과 dict
    """
    page_num = page_data.get("page", 0)
    bom_items = page_data.get("bom_table", [])
    components = page_data.get("components", [])

    # 1. 도면 컴포넌트를 (type, subtype)별로 그룹핑 & qty 합산
    drawing_groups = defaultdict(lambda: {"quantity": 0, "items": []})
    for comp in components:
        ctype = (comp.get("type") or "").lower()
        csubtype = (comp.get("subtype") or "").lower()
        qty = comp.get("quantity", 1)
        if isinstance(qty, str):
            try:
                qty = int(qty)
            except ValueError:
                qty = 1

        key = f"{ctype}:{csubtype}"
        drawing_groups[key]["quantity"] += qty
        drawing_groups[key]["items"].append(comp)

    # 2. BOM 아이템별 비교
    comparison_items = []
    matched_drawing_keys = set()

    for item in bom_items:
        comp_type, subtype, should_skip = _get_component_info_from_bom(item)

        if should_skip:
            comparison_items.append({
                "bom_letter": (item.get("letter_code") or "").strip(),
                "bom_description": (item.get("description") or "").strip(),
                "bom_quantity": str(item.get("quantity", "")),
                "bom_size": (item.get("size_inches") or "").strip(),
                "drawing_component": "",
                "drawing_quantity": "",
                "match_status": "N/A",
                "quantity_diff": 0,
                "notes": "비교 대상 아님 (gasket/bolt/paint 등)",
            })
            continue

        if not comp_type and not subtype:
            comparison_items.append({
                "bom_letter": (item.get("letter_code") or "").strip(),
                "bom_description": (item.get("description") or "").strip(),
                "bom_quantity": str(item.get("quantity", "")),
                "bom_size": (item.get("size_inches") or "").strip(),
                "drawing_component": "",
                "drawing_quantity": "",
                "match_status": "N/A",
                "quantity_diff": 0,
                "notes": "매핑 불가",
            })
            continue

        # 파이프 길이 단위(M)는 수량 비교 불가
        bom_qty_raw = item.get("quantity", "")
        if _is_pipe_length_qty(bom_qty_raw):
            comparison_items.append({
                "bom_letter": (item.get("letter_code") or "").strip(),
                "bom_description": (item.get("description") or "").strip(),
                "bom_quantity": str(bom_qty_raw),
                "bom_size": (item.get("size_inches") or "").strip(),
                "drawing_component": f"{comp_type}:{subtype}",
                "drawing_quantity": "",
                "match_status": "N/A",
                "quantity_diff": 0,
                "notes": "파이프 길이(M) - 수량 비교 불가",
            })
            continue

        bom_qty = _parse_bom_quantity(bom_qty_raw)

        # 도면에서 매칭 찾기: type:subtype 정확 매칭 → type만 매칭
        drawing_key = f"{comp_type}:{subtype}"
        drawing_qty = 0
        matched_key = None

        if drawing_key in drawing_groups:
            drawing_qty = drawing_groups[drawing_key]["quantity"]
            matched_key = drawing_key
        else:
            # subtype 퍼지 매칭: 같은 type 내에서 유사 subtype 검색
            for dk, dv in drawing_groups.items():
                dt, ds = dk.split(":", 1) if ":" in dk else (dk, "")
                if dt == comp_type and subtype and ds and (
                    subtype in ds or ds in subtype
                ):
                    drawing_qty = dv["quantity"]
                    matched_key = dk
                    break

        if matched_key:
            matched_drawing_keys.add(matched_key)

        # 비교 판정
        if matched_key is None:
            match_status = "BOM_ONLY"
            diff = 0
        elif abs(bom_qty - drawing_qty) < 0.01:
            match_status = "MATCH"
            diff = 0
        else:
            match_status = "MISMATCH"
            diff = drawing_qty - bom_qty

        comparison_items.append({
            "bom_letter": (item.get("letter_code") or "").strip(),
            "bom_description": (item.get("description") or "").strip(),
            "bom_quantity": str(bom_qty_raw) if bom_qty_raw else str(int(bom_qty)),
            "bom_size": (item.get("size_inches") or "").strip(),
            "drawing_component": f"{comp_type}:{subtype}" if comp_type else "",
            "drawing_quantity": drawing_qty if matched_key else "",
            "match_status": match_status,
            "quantity_diff": diff,
            "notes": "",
        })

    # 3. 도면에만 있고 BOM에 없는 컴포넌트 (DRAWING_ONLY)
    for dk, dv in drawing_groups.items():
        if dk in matched_drawing_keys:
            continue
        dt, ds = dk.split(":", 1) if ":" in dk else (dk, "")
        # 스킵 대상 제외
        if dt in ("support", "instrument"):
            continue
        comparison_items.append({
            "bom_letter": "",
            "bom_description": "",
            "bom_quantity": "",
            "bom_size": "",
            "drawing_component": dk,
            "drawing_quantity": dv["quantity"],
            "match_status": "DRAWING_ONLY",
            "quantity_diff": dv["quantity"],
            "notes": f"도면에만 존재: {ds} x{dv['quantity']}",
        })

    # 4. 요약 통계
    matched = sum(1 for ci in comparison_items if ci["match_status"] == "MATCH")
    mismatched = sum(1 for ci in comparison_items if ci["match_status"] == "MISMATCH")
    bom_only = sum(1 for ci in comparison_items if ci["match_status"] == "BOM_ONLY")
    drawing_only = sum(1 for ci in comparison_items if ci["match_status"] == "DRAWING_ONLY")
    na_count = sum(1 for ci in comparison_items if ci["match_status"] == "N/A")
    comparable = matched + mismatched + bom_only + drawing_only

    return {
        "page": page_num,
        "drawing_number": page_data.get("drawing_number", ""),
        "line_no": page_data.get("line_no", ""),
        "comparison_items": comparison_items,
        "summary": {
            "total_bom_items": len(bom_items),
            "comparable_items": comparable,
            "matched": matched,
            "mismatched": mismatched,
            "bom_only": bom_only,
            "drawing_only": drawing_only,
            "na_items": na_count,
            "match_rate": round(matched / max(1, comparable) * 100, 1),
        },
    }


def compare_all_pages(vlm_data: list[dict]) -> list[dict]:
    """전체 페이지에 대해 BOM vs Drawing 비교를 수행.

    Args:
        vlm_data: VLM 분석 결과 리스트 (페이지별)

    Returns:
        비교 결과 리스트
    """
    results = []
    for page_data in vlm_data:
        bom_table = page_data.get("bom_table", [])
        components = page_data.get("components", [])

        # BOM 테이블이나 컴포넌트가 있는 페이지만 비교
        if bom_table or components:
            try:
                comparison = compare_single_page(page_data)
                results.append(comparison)
            except Exception as e:
                logger.warning(f"Page {page_data.get('page', '?')} comparison failed: {e}")
                results.append({
                    "page": page_data.get("page", 0),
                    "comparison_items": [],
                    "summary": {
                        "total_bom_items": len(bom_table),
                        "comparable_items": 0,
                        "matched": 0, "mismatched": 0,
                        "bom_only": 0, "drawing_only": 0,
                        "na_items": 0, "match_rate": 0,
                    },
                    "error": str(e),
                })

    logger.info(f"BOM comparison completed: {len(results)} pages compared")
    total_matched = sum(c["summary"]["matched"] for c in results)
    total_mismatched = sum(c["summary"]["mismatched"] for c in results)
    total_comparable = sum(c["summary"]["comparable_items"] for c in results)
    overall_rate = round(total_matched / max(1, total_comparable) * 100, 1)
    logger.info(f"  Overall: {total_matched} matched, {total_mismatched} mismatched, "
                f"rate={overall_rate}%")

    return results
