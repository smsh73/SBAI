#!/usr/bin/env python3
"""4개 뷰를 치수 주석과 함께 렌더링하는 스크립트"""
import ezdxf
import numpy as np
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from pathlib import Path
from collections import defaultdict

DXF_PATH = Path(__file__).parent / "1. 260210-AI-SAMPLE.dxf"
OUTPUT_DIR = Path(__file__).parent
DIMLFAC = 75.01875305175781


def to_mm(val):
    return abs(val) * DIMLFAC


def load_dxf():
    doc = ezdxf.readfile(str(DXF_PATH))
    return doc


def get_entities_data(doc):
    """뷰별 엔티티 데이터 수집"""
    msp = doc.modelspace()
    VIEW_BOUNDS = {
        "plan": {"xmin": -10020, "xmax": -9920, "ymin": 3145, "ymax": 3215},
        "front": {"xmin": -9905, "xmax": -9805, "ymin": 3165, "ymax": 3190},
        "side": {"xmin": -9785, "xmax": -9715, "ymin": 3165, "ymax": 3190},
        "iso": {"xmin": -9915, "xmax": -9805, "ymin": 3055, "ymax": 3125},
    }

    lines_by_view = defaultdict(list)
    polys_by_view = defaultdict(list)

    for entity in msp:
        etype = entity.dxftype()
        if etype == "LINE":
            s, e = entity.dxf.start, entity.dxf.end
            cx, cy = (s.x + e.x) / 2, (s.y + e.y) / 2
            for vn, vb in VIEW_BOUNDS.items():
                if vb["xmin"] <= cx <= vb["xmax"] and vb["ymin"] <= cy <= vb["ymax"]:
                    lines_by_view[vn].append(((s.x, s.y), (e.x, e.y)))
                    break
        elif etype == "LWPOLYLINE":
            pts = list(entity.get_points(format="xy"))
            if pts:
                cx = sum(p[0] for p in pts) / len(pts)
                cy = sum(p[1] for p in pts) / len(pts)
                for vn, vb in VIEW_BOUNDS.items():
                    if vb["xmin"] <= cx <= vb["xmax"] and vb["ymin"] <= cy <= vb["ymax"]:
                        polys_by_view[vn].append(pts)
                        break

    return lines_by_view, polys_by_view, VIEW_BOUNDS


def find_major_grids(lines, polys, min_length=10.0):
    """주요 그리드라인의 좌표 추출"""
    h_lines = []  # (y좌표, x시작, x끝, 길이)
    v_lines = []  # (x좌표, y시작, y끝, 길이)

    all_segs = []
    for (x1, y1), (x2, y2) in lines:
        all_segs.append((x1, y1, x2, y2))
    for pts in polys:
        for i in range(len(pts) - 1):
            all_segs.append((pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1]))

    for x1, y1, x2, y2 in all_segs:
        dx, dy = abs(x2 - x1), abs(y2 - y1)
        if dy < 0.1 and dx > min_length:
            h_lines.append(((y1 + y2) / 2, min(x1, x2), max(x1, x2), dx))
        elif dx < 0.1 and dy > min_length:
            v_lines.append(((x1 + x2) / 2, min(y1, y2), max(y1, y2), dy))

    def cluster(values, tol=0.5):
        if not values:
            return []
        sv = sorted(values)
        clusters = [[sv[0]]]
        for v in sv[1:]:
            if v - clusters[-1][-1] < tol:
                clusters[-1].append(v)
            else:
                clusters.append([v])
        return [np.mean(c) for c in clusters]

    h_ys = cluster([l[0] for l in h_lines], tol=0.5)
    v_xs = cluster([l[0] for l in v_lines], tol=0.5)

    return h_ys, v_xs


def add_dimension_annotation(ax, p1, p2, offset, direction, color="#FF4444", fontsize=7):
    """치수선 주석 추가"""
    if direction == "h":  # 수평 치수 (Y 방향 오프셋)
        x1, x2 = p1[0], p2[0]
        y = p1[1] + offset
        dist_mm = to_mm(abs(x2 - x1))

        # 치수선
        ax.plot([x1, x1], [p1[1], y], color=color, linewidth=0.3, alpha=0.6)
        ax.plot([x2, x2], [p2[1], y], color=color, linewidth=0.3, alpha=0.6)
        ax.annotate("", xy=(x2, y), xytext=(x1, y),
                     arrowprops=dict(arrowstyle="<->", color=color, lw=0.6))
        ax.text((x1 + x2) / 2, y + offset * 0.15, f"{dist_mm:.0f}",
                ha="center", va="bottom" if offset > 0 else "top",
                fontsize=fontsize, color=color, fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.1", facecolor="white", edgecolor="none", alpha=0.85))

    elif direction == "v":  # 수직 치수 (X 방향 오프셋)
        y1, y2 = p1[1], p2[1]
        x = p1[0] + offset
        dist_mm = to_mm(abs(y2 - y1))

        ax.plot([p1[0], x], [y1, y1], color=color, linewidth=0.3, alpha=0.6)
        ax.plot([p2[0], x], [y2, y2], color=color, linewidth=0.3, alpha=0.6)
        ax.annotate("", xy=(x, y2), xytext=(x, y1),
                     arrowprops=dict(arrowstyle="<->", color=color, lw=0.6))
        ax.text(x + offset * 0.15, (y1 + y2) / 2, f"{dist_mm:.0f}",
                ha="left" if offset > 0 else "right", va="center",
                fontsize=fontsize, color=color, fontweight="bold",
                rotation=90,
                bbox=dict(boxstyle="round,pad=0.1", facecolor="white", edgecolor="none", alpha=0.85))


def render_view_with_dims(doc, view_name, bounds, lines, polys, filename, title,
                          dim_config=None):
    """뷰를 치수와 함께 렌더링"""
    msp = doc.modelspace()

    margin = 8
    xmin = bounds["xmin"] + margin
    xmax = bounds["xmax"] - margin
    ymin = bounds["ymin"] + margin
    ymax = bounds["ymax"] - margin

    width = xmax - xmin
    height = ymax - ymin
    aspect = width / height

    fig_h = max(10, 12)
    fig_w = max(12, fig_h * aspect)

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))

    ctx = RenderContext(doc)
    out = MatplotlibBackend(ax)
    Frontend(ctx, out).draw_layout(msp)

    # 뷰 영역 설정 (여유 공간 추가)
    pad_x = width * 0.12
    pad_y = height * 0.12
    ax.set_xlim(xmin - pad_x, xmax + pad_x)
    ax.set_ylim(ymin - pad_y, ymax + pad_y)
    ax.set_aspect("equal")

    # 치수 주석 추가
    if dim_config:
        for dim in dim_config:
            add_dimension_annotation(ax, **dim)

    # 스타일
    ax.set_title(title, fontsize=14, fontweight="bold", pad=15)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    # 스케일 정보 텍스트
    ax.text(0.02, 0.02, f"Scale: 1 unit = {DIMLFAC:.1f} mm",
            transform=ax.transAxes, fontsize=8, color="gray",
            verticalalignment="bottom")

    png_path = OUTPUT_DIR / filename
    fig.savefig(str(png_path), dpi=300, bbox_inches="tight",
                facecolor="white", edgecolor="none", pad_inches=0.3)
    plt.close(fig)
    print(f"  Saved: {png_path.name} ({png_path.stat().st_size / 1024:.0f} KB)")
    return png_path


# ============================================================
# 메인 실행
# ============================================================
if __name__ == "__main__":
    print("=== 치수 주석 포함 뷰 렌더링 ===\n")

    doc = load_dxf()
    lines_by_view, polys_by_view, VIEW_BOUNDS = get_entities_data(doc)

    # --- View 1: Plan (평면도) ---
    # 주요 그리드 분석
    h_ys, v_xs = find_major_grids(
        lines_by_view["plan"], polys_by_view["plan"], min_length=10)

    # 평면도: 전체 폭/높이 + 주요 그리드 간격
    plan_dims = []
    # 전체 가로 (상단)
    plan_dims.append({
        "p1": (-10010.20, 3205.50), "p2": (-9924.90, 3205.50),
        "offset": 5.0, "direction": "h", "color": "#FF2222", "fontsize": 8
    })
    # 전체 세로 (좌측)
    plan_dims.append({
        "p1": (-10010.20, 3149.50), "p2": (-10010.20, 3205.50),
        "offset": -5.0, "direction": "v", "color": "#FF2222", "fontsize": 8
    })

    # 주요 수평 그리드 간격 (우측에 표시) - 큰 간격만
    prev_y = None
    for y in sorted(h_ys):
        if prev_y is not None:
            gap = y - prev_y
            gap_mm = to_mm(gap)
            if gap_mm > 300:  # 300mm 이상 간격만 표시
                plan_dims.append({
                    "p1": (-9924.90, prev_y), "p2": (-9924.90, y),
                    "offset": 3.0, "direction": "v", "color": "#2288FF", "fontsize": 6
                })
        prev_y = y

    # 주요 수직 그리드 간격 (하단에 표시) - 큰 간격만
    prev_x = None
    for x in sorted(v_xs):
        if prev_x is not None:
            gap = x - prev_x
            gap_mm = to_mm(gap)
            if gap_mm > 300:
                plan_dims.append({
                    "p1": (prev_x, 3149.50), "p2": (x, 3149.50),
                    "offset": -3.0, "direction": "h", "color": "#2288FF", "fontsize": 6
                })
        prev_x = x

    print("Rendering View 1 - Plan...")
    render_view_with_dims(
        doc, "plan", VIEW_BOUNDS["plan"],
        lines_by_view["plan"], polys_by_view["plan"],
        "view1_plan_dims.png",
        "View 1 - Plan (Top View) - Dimensions in mm",
        dim_config=plan_dims
    )

    # --- View 2: Front Elevation ---
    front_dims = []
    # 전체 가로
    front_dims.append({
        "p1": (-9902.00, 3184.00), "p2": (-9809.00, 3184.00),
        "offset": 3.0, "direction": "h", "color": "#FF2222", "fontsize": 8
    })
    # 높이 (730mm에 해당)
    front_dims.append({
        "p1": (-9809.00, 3170.00), "p2": (-9809.00, 3179.50),
        "offset": 3.0, "direction": "v", "color": "#FF2222", "fontsize": 8
    })

    print("Rendering View 2 - Front Elevation...")
    render_view_with_dims(
        doc, "front", VIEW_BOUNDS["front"],
        lines_by_view["front"], polys_by_view["front"],
        "view2_front_dims.png",
        "View 2 - Front Elevation - Dimensions in mm",
        dim_config=front_dims
    )

    # --- View 3: Side Elevation ---
    side_dims = []
    # 전체 가로
    side_dims.append({
        "p1": (-9779.50, 3184.00), "p2": (-9722.00, 3184.00),
        "offset": 3.0, "direction": "h", "color": "#FF2222", "fontsize": 8
    })
    # 높이
    side_dims.append({
        "p1": (-9722.00, 3170.00), "p2": (-9722.00, 3179.50),
        "offset": 3.0, "direction": "v", "color": "#FF2222", "fontsize": 8
    })

    print("Rendering View 3 - Side Elevation...")
    render_view_with_dims(
        doc, "side", VIEW_BOUNDS["side"],
        lines_by_view["side"], polys_by_view["side"],
        "view3_side_dims.png",
        "View 3 - Side Elevation - Dimensions in mm",
        dim_config=side_dims
    )

    # --- View 4: Isometric ---
    iso_dims = []
    # 등각 투영도는 좌표 왜곡이 있으므로 전체 범위만 표시
    iso_dims.append({
        "p1": (-9909.30, 3060.29), "p2": (-9808.99, 3060.29),
        "offset": -4.0, "direction": "h", "color": "#FF2222", "fontsize": 8
    })
    iso_dims.append({
        "p1": (-9808.99, 3060.29), "p2": (-9808.99, 3122.52),
        "offset": 4.0, "direction": "v", "color": "#FF2222", "fontsize": 8
    })

    print("Rendering View 4 - Isometric...")
    render_view_with_dims(
        doc, "iso", VIEW_BOUNDS["iso"],
        lines_by_view["iso"], polys_by_view["iso"],
        "view4_iso_dims.png",
        "View 4 - Isometric View - Dimensions in mm",
        dim_config=iso_dims
    )

    print("\n=== All views rendered with dimensions ===")
