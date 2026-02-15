#!/usr/bin/env python3
"""DXF 좌표로부터 실제 치수를 역산하는 분석 스크립트
DIMLFAC = 75.01875 을 사용하여 도면 좌표 → 실제 mm 변환
"""
import ezdxf
import numpy as np
from pathlib import Path
from collections import defaultdict

DXF_PATH = Path(__file__).parent / "1. 260210-AI-SAMPLE.dxf"
DIMLFAC = 75.01875305175781  # 치수 축척 비율

doc = ezdxf.readfile(str(DXF_PATH))
msp = doc.modelspace()

# ============================================================
# 1단계: 모든 엔티티에서 주요 좌표 수집
# ============================================================
print("=" * 70)
print("DXF 치수 역산 분석 보고서")
print(f"DIMLFAC (스케일 팩터): {DIMLFAC:.4f}")
print(f"1 도면단위 = {DIMLFAC:.2f} mm")
print("=" * 70)

# 뷰별 엔티티 분류 (이전 클러스터링 결과 기반)
VIEW_BOUNDS = {
    "View 1 (Plan)": {"xmin": -10020, "xmax": -9920, "ymin": 3145, "ymax": 3215},
    "View 2 (Front Elev.)": {"xmin": -9905, "xmax": -9805, "ymin": 3165, "ymax": 3190},
    "View 3 (Side Elev.)": {"xmin": -9785, "xmax": -9715, "ymin": 3165, "ymax": 3190},
    "View 4 (Isometric)": {"xmin": -9915, "xmax": -9805, "ymin": 3055, "ymax": 3125},
}


def point_in_view(x, y, bounds):
    return bounds["xmin"] <= x <= bounds["xmax"] and bounds["ymin"] <= y <= bounds["ymax"]


def classify_view(cx, cy):
    for name, b in VIEW_BOUNDS.items():
        if point_in_view(cx, cy, b):
            return name
    return "Unknown"


# ============================================================
# 2단계: 뷰별로 수평/수직 주요 선분 추출
# ============================================================
lines_by_view = defaultdict(list)
polys_by_view = defaultdict(list)

for entity in msp:
    etype = entity.dxftype()
    if etype == "LINE":
        s = entity.dxf.start
        e = entity.dxf.end
        cx, cy = (s.x + e.x) / 2, (s.y + e.y) / 2
        view = classify_view(cx, cy)
        lines_by_view[view].append(((s.x, s.y), (e.x, e.y)))
    elif etype == "LWPOLYLINE":
        pts = list(entity.get_points(format="xy"))
        if pts:
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            view = classify_view(cx, cy)
            polys_by_view[view].append(pts)


def to_mm(drawing_units):
    """도면 단위를 mm로 변환"""
    return abs(drawing_units) * DIMLFAC


# ============================================================
# 3단계: 주요 그리드라인 및 부재 간격 분석 (View 1 - 평면도)
# ============================================================
def analyze_grid(view_name, lines, polys):
    """수평/수직 그리드라인을 감지하고 간격 계산"""
    all_h_lines = []  # 수평선 (y좌표 기준)
    all_v_lines = []  # 수직선 (x좌표 기준)

    for (x1, y1), (x2, y2) in lines:
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        length = np.sqrt(dx**2 + dy**2)

        if length < 0.5:
            continue

        # 수평선 (dy가 매우 작음)
        if dy < 0.1 and dx > 2.0:
            all_h_lines.append((min(x1, x2), max(x1, x2), (y1 + y2) / 2, dx))
        # 수직선 (dx가 매우 작음)
        elif dx < 0.1 and dy > 2.0:
            all_v_lines.append((min(y1, y2), max(y1, y2), (x1 + x2) / 2, dy))

    # 폴리라인에서도 긴 수평/수직 세그먼트 추출
    for pts in polys:
        for i in range(len(pts) - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]
            dx = abs(x2 - x1)
            dy = abs(y2 - y1)

            if dy < 0.1 and dx > 2.0:
                all_h_lines.append((min(x1, x2), max(x1, x2), (y1 + y2) / 2, dx))
            elif dx < 0.1 and dy > 2.0:
                all_v_lines.append((min(y1, y2), max(y1, y2), (x1 + x2) / 2, dy))

    # Y좌표별 수평선 그룹핑 (0.3 단위 이내는 동일 그리드)
    h_y_values = sorted(set([round(l[2], 1) for l in all_h_lines]))
    v_x_values = sorted(set([round(l[2], 1) for l in all_v_lines]))

    # 그리드 클러스터링
    def cluster_values(values, tolerance=0.5):
        if not values:
            return []
        clusters = [[values[0]]]
        for v in values[1:]:
            if v - clusters[-1][-1] < tolerance:
                clusters[-1].append(v)
            else:
                clusters.append([v])
        return [np.mean(c) for c in clusters]

    h_grids = cluster_values(h_y_values, tolerance=0.5)
    v_grids = cluster_values(v_x_values, tolerance=0.5)

    # 긴 선분만 필터링 (주요 그리드라인)
    long_h_lines = [l for l in all_h_lines if l[3] > 10]
    long_v_lines = [l for l in all_v_lines if l[3] > 10]

    long_h_y = sorted(set([round(l[2], 1) for l in long_h_lines]))
    long_v_x = sorted(set([round(l[2], 1) for l in long_v_lines]))

    major_h = cluster_values(long_h_y, tolerance=0.5)
    major_v = cluster_values(long_v_x, tolerance=0.5)

    return {
        "h_lines": len(all_h_lines),
        "v_lines": len(all_v_lines),
        "major_h_grids": major_h,
        "major_v_grids": major_v,
        "all_h_grids": h_grids,
        "all_v_grids": v_grids,
    }


# ============================================================
# 4단계: 각 뷰 분석 실행
# ============================================================
for view_name in VIEW_BOUNDS:
    lines = lines_by_view.get(view_name, [])
    polys = polys_by_view.get(view_name, [])

    print(f"\n{'=' * 70}")
    print(f"  {view_name}")
    print(f"  LINE: {len(lines)}, POLYLINE: {len(polys)}")
    print(f"{'=' * 70}")

    result = analyze_grid(view_name, lines, polys)

    # 주요 수평 그리드 간격
    major_h = result["major_h_grids"]
    major_v = result["major_v_grids"]

    if major_h and len(major_h) >= 2:
        print(f"\n  [수평 주요 그리드라인] (Y좌표) - {len(major_h)}개")
        print(f"  {'Y 좌표':>12}  {'간격(units)':>12}  {'간격(mm)':>12}")
        print(f"  {'-'*12}  {'-'*12}  {'-'*12}")
        for i, y in enumerate(major_h):
            if i == 0:
                print(f"  {y:12.2f}  {'---':>12}  {'---':>12}")
            else:
                gap = y - major_h[i - 1]
                mm = to_mm(gap)
                print(f"  {y:12.2f}  {gap:12.2f}  {mm:10.0f} mm")

        total = major_h[-1] - major_h[0]
        print(f"  {'':>12}  {'TOTAL':>12}  {to_mm(total):10.0f} mm")

    if major_v and len(major_v) >= 2:
        print(f"\n  [수직 주요 그리드라인] (X좌표) - {len(major_v)}개")
        print(f"  {'X 좌표':>12}  {'간격(units)':>12}  {'간격(mm)':>12}")
        print(f"  {'-'*12}  {'-'*12}  {'-'*12}")
        for i, x in enumerate(major_v):
            if i == 0:
                print(f"  {x:12.2f}  {'---':>12}  {'---':>12}")
            else:
                gap = x - major_v[i - 1]
                mm = to_mm(gap)
                print(f"  {x:12.2f}  {gap:12.2f}  {mm:10.0f} mm")

        total = major_v[-1] - major_v[0]
        print(f"  {'':>12}  {'TOTAL':>12}  {to_mm(total):10.0f} mm")

    # 전체 범위
    if lines or polys:
        all_x = []
        all_y = []
        for (x1, y1), (x2, y2) in lines:
            all_x.extend([x1, x2])
            all_y.extend([y1, y2])
        for pts in polys:
            for x, y in pts:
                all_x.append(x)
                all_y.append(y)

        width = max(all_x) - min(all_x)
        height = max(all_y) - min(all_y)
        print(f"\n  [전체 범위]")
        print(f"  가로: {width:.2f} units = {to_mm(width):.0f} mm")
        print(f"  세로: {height:.2f} units = {to_mm(height):.0f} mm")


# ============================================================
# 5단계: View 1 평면도 부재 상세 분석
# ============================================================
print(f"\n{'=' * 70}")
print("  View 1 (Plan) - 부재(Member) 상세 분석")
print(f"{'=' * 70}")

# LWPOLYLINE에서 닫힌 사각형 (부재 단면) 감지
view1_polys = polys_by_view.get("View 1 (Plan)", [])
view1_lines = lines_by_view.get("View 1 (Plan)", [])

rectangles = []
for pts in view1_polys:
    # 닫힌 사각형: 4~5개 점, 거의 직교
    n = len(pts)
    if n in (4, 5):
        xs = [p[0] for p in pts[:4]]
        ys = [p[1] for p in pts[:4]]
        w = max(xs) - min(xs)
        h = max(ys) - min(ys)
        if w > 0.1 and h > 0.1:
            rectangles.append({
                "cx": (min(xs) + max(xs)) / 2,
                "cy": (min(ys) + max(ys)) / 2,
                "w": w, "h": h,
                "w_mm": to_mm(w), "h_mm": to_mm(h),
            })

# 부재 크기별 그룹핑
size_groups = defaultdict(list)
for r in rectangles:
    # 크기를 10mm 단위로 반올림
    w_r = round(r["w_mm"] / 10) * 10
    h_r = round(r["h_mm"] / 10) * 10
    key = (min(w_r, h_r), max(w_r, h_r))
    size_groups[key].append(r)

print(f"\n  감지된 사각형 부재: {len(rectangles)}개")
print(f"\n  {'크기 (mm)':>20}  {'수량':>6}")
print(f"  {'-'*20}  {'-'*6}")
for (w, h), items in sorted(size_groups.items(), key=lambda x: -len(x[1])):
    print(f"  {w:>8.0f} x {h:<8.0f}  {len(items):>6}")


# ============================================================
# 6단계: 주요 부재 간 거리 계산
# ============================================================
print(f"\n{'=' * 70}")
print("  View 1 (Plan) - 주요 부재 간 중심거리")
print(f"{'=' * 70}")

# 큰 사각형 (부재 단면이 아닌 외곽 프레임은 제외)
# 특정 크기 범위의 부재들만 선택
structural_members = [r for r in rectangles if 50 < r["w_mm"] < 500 and 50 < r["h_mm"] < 500]

if structural_members:
    # X좌표별 정렬하여 수직 부재(컬럼) 간격 분석
    cx_values = sorted(set([round(r["cx"], 1) for r in structural_members]))
    cy_values = sorted(set([round(r["cy"], 1) for r in structural_members]))

    def cluster_values2(values, tolerance=1.0):
        if not values:
            return []
        clusters = [[values[0]]]
        for v in values[1:]:
            if v - clusters[-1][-1] < tolerance:
                clusters[-1].append(v)
            else:
                clusters.append([v])
        return sorted([np.mean(c) for c in clusters])

    col_x = cluster_values2(cx_values, tolerance=1.5)
    col_y = cluster_values2(cy_values, tolerance=1.5)

    if len(col_x) >= 2:
        print(f"\n  [부재 X방향 배치 간격] - {len(col_x)}개 위치")
        for i in range(1, len(col_x)):
            gap = col_x[i] - col_x[i-1]
            print(f"    #{i} → #{i+1}: {gap:.2f} units = {to_mm(gap):.0f} mm")

    if len(col_y) >= 2:
        print(f"\n  [부재 Y방향 배치 간격] - {len(col_y)}개 위치")
        for i in range(1, len(col_y)):
            gap = col_y[i] - col_y[i-1]
            print(f"    #{i} → #{i+1}: {gap:.2f} units = {to_mm(gap):.0f} mm")

print(f"\n{'=' * 70}")
print("  분석 완료")
print(f"{'=' * 70}")
