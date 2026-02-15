"""Excel 생성 서비스 - 밸브 리스트 + PIPE BOM"""
import json
import openpyxl
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter
from copy import copy
from pathlib import Path
from collections import defaultdict, OrderedDict
import logging

logger = logging.getLogger(__name__)

# Styles
HEADER_FONT = Font(name="Arial", size=10, bold=True, color="FFFFFF")
HEADER_FILL = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
SUBHEADER_FILL = PatternFill(start_color="D6E4F0", end_color="D6E4F0", fill_type="solid")
DATA_FONT = Font(name="Arial", size=9)
BORDER = Border(
    left=Side(style="thin"), right=Side(style="thin"),
    top=Side(style="thin"), bottom=Side(style="thin")
)
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)

# Piping class → material mapping
PIPING_CLASS_MAP = {
    "CS3": {"piping_spec": "ACS10B3", "body": "ASTM A536", "trim": "B62",
            "flange": "150 Lbs RF WN\n(A105)", "pipe_mat": "ASTM A53 Gr.B _ POLYETHYLENE LINING INSIDE"},
    "CS2": {"piping_spec": "ACS10B2", "body": "ASTM A536", "trim": "B62",
            "flange": "150 Lbs RF WN\n(A105)", "pipe_mat": "ASTM A53 Gr.B _ POLYETHYLENE LINING INSIDE"},
}

SSW_SPEC = {
    "piping_spec": "BCS21B3", "body": "ASTM A536", "trim": "B62",
    "flange": "150 Lbs RF WN\n(A105)", "pipe_mat": "ASTM A53 Gr.B _ POLYETHYLENE LINING INSIDE"
}

DESIGN_CONDITIONS = {
    "SW": {"press": 6.5, "temp": 60},
    "SSW": {"press": 10, "temp": 60},
    "CFW": {"press": 6.5, "temp": 90},
    "FW": {"press": 6.5, "temp": 60},
}


def _style_header(ws, row, max_col):
    for col in range(1, max_col + 1):
        cell = ws.cell(row=row, column=col)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = CENTER
        cell.border = BORDER


def _style_data(ws, row, max_col, font=None, fill=None):
    for col in range(1, max_col + 1):
        cell = ws.cell(row=row, column=col)
        cell.font = font or DATA_FONT
        cell.alignment = CENTER
        cell.border = BORDER
        if fill:
            cell.fill = fill


def _get_piping_spec(valve):
    fluid = valve.get("fluid", "")
    piping_class = valve.get("piping_class", "CS3")
    if fluid == "SW" and valve["tag"].startswith("SSW"):
        return SSW_SPEC["piping_spec"]
    return PIPING_CLASS_MAP.get(piping_class, PIPING_CLASS_MAP["CS3"])["piping_spec"]


def _get_material_info(valve):
    piping_class = valve.get("piping_class", "CS3")
    fluid = valve.get("fluid", "")
    if fluid == "SW" and valve["tag"].startswith("SSW"):
        return SSW_SPEC
    return PIPING_CLASS_MAP.get(piping_class, PIPING_CLASS_MAP["CS3"])


def _get_design_conditions(valve):
    tag = valve.get("tag", "")
    fluid = valve.get("fluid", "")
    if tag.startswith("SSW"):
        return DESIGN_CONDITIONS.get("SSW", {"press": 10, "temp": 60})
    return DESIGN_CONDITIONS.get(fluid, {"press": 6.5, "temp": 60})


def generate_valve_excel(valves: list[dict], output_path: str, template_path: str = None) -> str:
    """밸브 리스트 Excel 생성"""
    if template_path and Path(template_path).exists():
        wb = openpyxl.load_workbook(template_path)
        ws = wb.active if "Manual" not in wb.sheetnames else wb["Manual"]

        # 참조 스타일 저장
        ref_styles = {}
        if ws.max_row >= 8:
            for cell in ws[8]:
                ref_styles[cell.column] = {
                    "font": copy(cell.font),
                    "alignment": copy(cell.alignment),
                    "border": copy(cell.border),
                    "fill": copy(cell.fill),
                }

        # 기존 데이터 클리어
        for row_num in range(8, ws.max_row + 1):
            for col in range(1, 27):
                ws.cell(row=row_num, column=col).value = None
    else:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Valve List"
        ref_styles = {}

        # 헤더 생성
        headers = ["NO.", "TAG", "PIPING SPEC", "LOCATION", "DESCRIPTION", "FLUID",
                    "DESIGN PRESS", "DESIGN TEMP", "VALVE TYPE", "SUB TYPE",
                    "BODY", "TRIM", "SIZE", "PRESS RATING", "FLANGE",
                    "END IN", "END OUT", "PIPE MAT", "SCH IN", "SCH OUT",
                    "EXT BONNET", "CLASS CERT", "LS OPEN", "LS CLOSE", "LOCK DEV", "REMARK"]
        for col, h in enumerate(headers, 1):
            ws.cell(row=1, column=col, value=h)
        _style_header(ws, 1, len(headers))

    # 밸브 분류
    manual_valves = sorted(
        [v for v in valves if v.get("valve_type") != "CONTROL"],
        key=lambda v: v["tag"]
    )
    control_valves = sorted(
        [v for v in valves if v.get("valve_type") == "CONTROL"],
        key=lambda v: v["tag"]
    )

    # Manual Valve 섹션
    start_row = 7 if template_path else 2
    if template_path:
        ws.cell(row=start_row, column=1, value="1. Manual Valve")

    for i, valve in enumerate(manual_valves):
        row = start_row + 1 + i
        mat_info = _get_material_info(valve)
        design = _get_design_conditions(valve)
        sch = valve.get("schedule", "STD")

        ws.cell(row=row, column=1, value=i + 1)
        ws.cell(row=row, column=2, value=valve["tag"])
        ws.cell(row=row, column=3, value=_get_piping_spec(valve))
        ws.cell(row=row, column=4, value=valve.get("location", ""))
        ws.cell(row=row, column=5, value=valve.get("description", ""))
        ws.cell(row=row, column=6, value=valve.get("fluid", ""))
        ws.cell(row=row, column=7, value=design["press"])
        ws.cell(row=row, column=8, value=design["temp"])
        ws.cell(row=row, column=9, value=valve.get("valve_type", ""))
        ws.cell(row=row, column=10, value=valve.get("valve_subtype", ""))
        ws.cell(row=row, column=11, value=mat_info["body"])
        ws.cell(row=row, column=12, value=mat_info["trim"])
        ws.cell(row=row, column=13, value=int(valve["size"]) if valve.get("size", "").isdigit() else valve.get("size", ""))
        ws.cell(row=row, column=14, value="ANSI")
        ws.cell(row=row, column=15, value=mat_info["flange"])
        ws.cell(row=row, column=16, value="FLG")
        ws.cell(row=row, column=17, value="FLG")
        ws.cell(row=row, column=18, value=mat_info["pipe_mat"])
        ws.cell(row=row, column=19, value=sch)
        ws.cell(row=row, column=20, value=sch)
        ws.cell(row=row, column=21, value="-")
        ws.cell(row=row, column=22, value=3)
        ws.cell(row=row, column=23, value="-")
        ws.cell(row=row, column=24, value="-")
        ws.cell(row=row, column=25, value="-")
        ws.cell(row=row, column=26, value=f"Sheet {valve.get('sheet', '')}")

        for col in range(1, 27):
            cell = ws.cell(row=row, column=col)
            if col in ref_styles:
                cell.font = copy(ref_styles[col]["font"])
                cell.alignment = copy(ref_styles[col]["alignment"])
                cell.border = copy(ref_styles[col]["border"])

    # Control Valve 섹션
    ctrl_start = start_row + 1 + len(manual_valves) + 1
    ws.cell(row=ctrl_start, column=1, value="2. Control Valve")
    ws.cell(row=ctrl_start, column=1).font = Font(name="Arial", size=10, bold=True)

    for i, valve in enumerate(control_valves):
        row = ctrl_start + 1 + i
        mat_info = _get_material_info(valve)
        design = _get_design_conditions(valve)
        sch = valve.get("schedule", "STD")

        ws.cell(row=row, column=1, value=i + 1)
        ws.cell(row=row, column=2, value=valve["tag"])
        ws.cell(row=row, column=3, value=_get_piping_spec(valve))
        ws.cell(row=row, column=4, value=valve.get("location", ""))
        ws.cell(row=row, column=5, value=valve.get("description", ""))
        ws.cell(row=row, column=6, value=valve.get("fluid", ""))
        ws.cell(row=row, column=7, value=design["press"])
        ws.cell(row=row, column=8, value=design["temp"])
        ws.cell(row=row, column=9, value="CONTROL")
        ws.cell(row=row, column=10, value=valve.get("valve_subtype", ""))
        ws.cell(row=row, column=11, value=mat_info["body"])
        ws.cell(row=row, column=12, value=mat_info["trim"])
        ws.cell(row=row, column=13, value=int(valve["size"]) if valve.get("size", "").isdigit() else valve.get("size", ""))
        ws.cell(row=row, column=14, value="ANSI")
        ws.cell(row=row, column=15, value=mat_info["flange"])
        ws.cell(row=row, column=16, value="FLG")
        ws.cell(row=row, column=17, value="FLG")
        ws.cell(row=row, column=18, value=mat_info["pipe_mat"])
        ws.cell(row=row, column=19, value=sch)
        ws.cell(row=row, column=20, value=sch)
        ws.cell(row=row, column=21, value="-")
        ws.cell(row=row, column=22, value=3)
        ws.cell(row=row, column=23, value="-")
        ws.cell(row=row, column=24, value="-")
        ws.cell(row=row, column=25, value="-")
        ws.cell(row=row, column=26, value=f"Sheet {valve.get('sheet', '')}")

        for col in range(1, 27):
            cell = ws.cell(row=row, column=col)
            if col in ref_styles:
                cell.font = copy(ref_styles[col]["font"])
                cell.alignment = copy(ref_styles[col]["alignment"])
                cell.border = copy(ref_styles[col]["border"])

    # 합계
    summary_row = ctrl_start + len(control_valves) + 2
    ws.cell(row=summary_row, column=1, value="TOTAL")
    ws.cell(row=summary_row, column=1).font = Font(name="Arial", size=10, bold=True)
    ws.cell(row=summary_row, column=2, value=f"Manual: {len(manual_valves)}, Control: {len(control_valves)}, Total: {len(valves)}")
    ws.cell(row=summary_row, column=2).font = Font(name="Arial", size=10, bold=True)

    wb.save(output_path)
    logger.info(f"Valve Excel saved: {output_path} ({len(valves)} valves)")
    return output_path


def generate_pipe_bom_excel(pages_data: list[dict], output_path: str) -> str:
    """PIPE BOM Excel 생성 (4개 시트)"""
    wb = openpyxl.Workbook()

    # === Sheet 1: Pipe Piece Summary ===
    ws1 = wb.active
    ws1.title = "Pipe Piece Summary"

    headers1 = ["NO.", "Page", "Pipe Piece No.", "Sub-pieces", "Weld Count",
                 "Loose Parts", "Pipe Lengths (mm)", "Total Length (mm)", "Revision Notes"]
    for col, h in enumerate(headers1, 1):
        ws1.cell(row=1, column=col, value=h)
    _style_header(ws1, 1, len(headers1))

    row = 2
    total_welds = 0
    total_length = 0
    piece_no = 0

    for pd in pages_data:
        if not pd.get("pipe_pieces"):
            continue
        piece_no += 1
        dims = pd.get("dimensions_mm", [])
        total_dim = sum(dims) if dims else 0
        total_length += total_dim
        total_welds += pd.get("weld_count", 0)

        dims_str = ", ".join(str(d) for d in dims)
        other_dims = pd.get("other_dims", [])
        if other_dims:
            dims_str += (" + " if dims_str else "") + ", ".join(other_dims)

        rev = "; ".join(pd.get("revision_notes", []))

        ws1.cell(row=row, column=1, value=piece_no)
        ws1.cell(row=row, column=2, value=pd["page"])
        ws1.cell(row=row, column=3, value=", ".join(pd["pipe_pieces"]))
        ws1.cell(row=row, column=4, value=len(pd["pipe_pieces"]))
        ws1.cell(row=row, column=5, value=pd.get("weld_count", 0))
        ws1.cell(row=row, column=6, value="Yes" if pd.get("has_loose") else "-")
        ws1.cell(row=row, column=7, value=dims_str if dims_str else "-")
        ws1.cell(row=row, column=8, value=total_dim if total_dim > 0 else "-")
        ws1.cell(row=row, column=9, value=rev if rev else "-")
        _style_data(ws1, row, len(headers1))
        row += 1

    # 합계
    ws1.cell(row=row + 1, column=1, value="TOTAL")
    ws1.cell(row=row + 1, column=4, value=sum(len(p.get("pipe_pieces", [])) for p in pages_data))
    ws1.cell(row=row + 1, column=5, value=total_welds)
    ws1.cell(row=row + 1, column=8, value=total_length if total_length > 0 else "-")
    _style_data(ws1, row + 1, len(headers1),
                font=Font(name="Arial", size=10, bold=True),
                fill=PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid"))

    for i, w in enumerate([6, 6, 45, 10, 10, 10, 30, 15, 40], 1):
        ws1.column_dimensions[get_column_letter(i)].width = w

    # === Sheet 2: Weld Item Detail ===
    ws2 = wb.create_sheet("Weld Item Detail")
    headers2 = ["NO.", "Page", "Pipe Piece", "Item No.", "Item Type", "Notes"]
    for col, h in enumerate(headers2, 1):
        ws2.cell(row=1, column=col, value=h)
    _style_header(ws2, 1, len(headers2))

    row = 2
    item_no = 0
    for pd in pages_data:
        for weld in pd.get("weld_items", []):
            item_no += 1
            piece_str = ", ".join(pd.get("pipe_pieces", []))
            item_type = "Field Fit Weld (+100mm)" if weld.startswith("FFW") else "Shop Weld"
            ws2.cell(row=row, column=1, value=item_no)
            ws2.cell(row=row, column=2, value=pd["page"])
            ws2.cell(row=row, column=3, value=piece_str)
            ws2.cell(row=row, column=4, value=weld)
            ws2.cell(row=row, column=5, value=item_type)
            ws2.cell(row=row, column=6, value="-")
            _style_data(ws2, row, len(headers2))
            row += 1

    for i, w in enumerate([6, 6, 45, 10, 25, 20], 1):
        ws2.column_dimensions[get_column_letter(i)].width = w

    # === Sheet 3: Weld Quantity Summary ===
    ws3 = wb.create_sheet("Weld Quantity Summary")

    piece_summary = OrderedDict()
    for pd in pages_data:
        for pp in pd.get("pipe_pieces", []):
            base = pp.rsplit("-", 1)[0]
            if base not in piece_summary:
                piece_summary[base] = {
                    "sub_pieces": [], "shop_welds": 0, "field_welds": 0,
                    "total_welds": 0, "pages": set(), "dims": [], "has_loose": False,
                }
            piece_summary[base]["sub_pieces"].append(pp)
            piece_summary[base]["pages"].add(pd["page"])
            if pd.get("has_loose"):
                piece_summary[base]["has_loose"] = True

        if pd.get("pipe_pieces"):
            base = pd["pipe_pieces"][0].rsplit("-", 1)[0]
            for w in pd.get("weld_items", []):
                if w.startswith("FFW"):
                    piece_summary[base]["field_welds"] += 1
                else:
                    piece_summary[base]["shop_welds"] += 1
                piece_summary[base]["total_welds"] += 1
            for d in pd.get("dimensions_mm", []):
                piece_summary[base]["dims"].append(d)

    headers3 = ["NO.", "Pipe Piece Base", "Sub-piece Count", "Shop Welds",
                 "Field Welds", "Total Welds", "Has Loose", "Pipe Lengths (mm)",
                 "Total Length (mm)", "Pages"]
    for col, h in enumerate(headers3, 1):
        ws3.cell(row=1, column=col, value=h)
    _style_header(ws3, 1, len(headers3))

    row = 2
    grand_shop = grand_field = grand_total = grand_length = 0

    for idx, (base, info) in enumerate(sorted(piece_summary.items()), 1):
        total_len = sum(info["dims"]) if info["dims"] else 0
        grand_shop += info["shop_welds"]
        grand_field += info["field_welds"]
        grand_total += info["total_welds"]
        grand_length += total_len

        ws3.cell(row=row, column=1, value=idx)
        ws3.cell(row=row, column=2, value=base)
        ws3.cell(row=row, column=3, value=len(set(info["sub_pieces"])))
        ws3.cell(row=row, column=4, value=info["shop_welds"])
        ws3.cell(row=row, column=5, value=info["field_welds"])
        ws3.cell(row=row, column=6, value=info["total_welds"])
        ws3.cell(row=row, column=7, value="Yes" if info["has_loose"] else "-")
        ws3.cell(row=row, column=8, value=", ".join(str(d) for d in info["dims"]) if info["dims"] else "-")
        ws3.cell(row=row, column=9, value=total_len if total_len > 0 else "-")
        ws3.cell(row=row, column=10, value=", ".join(str(p) for p in sorted(info["pages"])))
        _style_data(ws3, row, len(headers3))
        row += 1

    ws3.cell(row=row + 1, column=1, value="TOTAL")
    ws3.cell(row=row + 1, column=3, value=sum(len(set(v["sub_pieces"])) for v in piece_summary.values()))
    ws3.cell(row=row + 1, column=4, value=grand_shop)
    ws3.cell(row=row + 1, column=5, value=grand_field)
    ws3.cell(row=row + 1, column=6, value=grand_total)
    ws3.cell(row=row + 1, column=9, value=grand_length if grand_length > 0 else "-")
    _style_data(ws3, row + 1, len(headers3),
                font=Font(name="Arial", size=10, bold=True),
                fill=PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid"))

    for i, w in enumerate([6, 18, 15, 12, 12, 12, 10, 30, 15, 15], 1):
        ws3.column_dimensions[get_column_letter(i)].width = w

    # === Sheet 4: Statistics ===
    ws4 = wb.create_sheet("Statistics")
    stats = [
        ("PIPE BOM STATISTICS", ""),
        ("", ""),
        ("Total Pages", len(pages_data)),
        ("Total Pipe Pieces", sum(len(p.get("pipe_pieces", [])) for p in pages_data)),
        ("Unique Base Pieces", len(piece_summary)),
        ("", ""),
        ("WELD SUMMARY", ""),
        ("Total Shop Welds", grand_shop),
        ("Total Field Welds (FFW)", grand_field),
        ("Total Welds", grand_total),
        ("", ""),
        ("PIPE LENGTH SUMMARY", ""),
        ("Total Measured Length (mm)", grand_length),
        ("Total Measured Length (m)", round(grand_length / 1000, 2) if grand_length else 0),
        ("", ""),
        ("LOOSE PARTS", ""),
        ("Pages with Loose Parts", sum(1 for p in pages_data if p.get("has_loose"))),
    ]

    for r, (label, value) in enumerate(stats, 1):
        ws4.cell(row=r, column=1, value=label)
        ws4.cell(row=r, column=2, value=value)
        if label and not value and label == label.upper():
            ws4.cell(row=r, column=1).font = Font(name="Arial", size=11, bold=True)
        else:
            ws4.cell(row=r, column=1).font = Font(name="Arial", size=10)
            ws4.cell(row=r, column=2).font = Font(name="Arial", size=10)

    ws4.column_dimensions["A"].width = 35
    ws4.column_dimensions["B"].width = 50

    wb.save(output_path)
    logger.info(f"Pipe BOM Excel saved: {output_path}")
    return output_path
