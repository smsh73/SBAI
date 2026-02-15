"""DXF 렌더링 & 분석 서비스 - render_dxf.py + render_views.py + render_with_dims.py + analyze_dimensions.py 통합"""
import ezdxf
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
from pathlib import Path
from collections import defaultdict
import logging
import json

logger = logging.getLogger(__name__)

DIMLFAC = 75.01875305175781
MARGIN = 5

# 4개 뷰 영역 정의 (기본값 - 클러스터링으로 동적 감지도 가능)
DEFAULT_VIEWS = {
    "view1_plan": {
        "label": "View 1 - Plan (평면도)",
        "xmin": -10016.83 - MARGIN, "xmax": -9924.67 + MARGIN,
        "ymin": 3148.17 - MARGIN, "ymax": 3211.66 + MARGIN,
    },
    "view2_elevation_front": {
        "label": "View 2 - Front Elevation (정면도)",
        "xmin": -9902.00 - MARGIN, "xmax": -9808.95 + MARGIN,
        "ymin": 3169.80 - MARGIN, "ymax": 3184.06 + MARGIN,
    },
    "view3_elevation_side": {
        "label": "View 3 - Side Elevation (측면도)",
        "xmin": -9779.52 - MARGIN, "xmax": -9722.00 + MARGIN,
        "ymin": 3169.80 - MARGIN, "ymax": 3184.06 + MARGIN,
    },
    "view4_isometric": {
        "label": "View 4 - Isometric (등각 투영도)",
        "xmin": -9909.30 - MARGIN, "xmax": -9808.99 + MARGIN,
        "ymin": 3060.29 - MARGIN, "ymax": 3122.52 + MARGIN,
    },
}

VIEW_BOUNDS = {
    "plan": {"xmin": -10020, "xmax": -9920, "ymin": 3145, "ymax": 3215},
    "front": {"xmin": -9905, "xmax": -9805, "ymin": 3165, "ymax": 3190},
    "side": {"xmin": -9785, "xmax": -9715, "ymin": 3165, "ymax": 3190},
    "iso": {"xmin": -9915, "xmax": -9805, "ymin": 3055, "ymax": 3125},
}


def to_mm(val):
    return abs(val) * DIMLFAC


def _detect_views(doc) -> dict:
    """엔티티 클러스터링으로 뷰 영역 자동 감지"""
    msp = doc.modelspace()
    boxes = []
    for entity in msp:
        etype = entity.dxftype()
        if etype == "LINE":
            s, e = entity.dxf.start, entity.dxf.end
            boxes.append(((s.x + e.x) / 2, (s.y + e.y) / 2))
        elif etype == "LWPOLYLINE":
            pts = list(entity.get_points(format="xy"))
            if pts:
                cx = sum(p[0] for p in pts) / len(pts)
                cy = sum(p[1] for p in pts) / len(pts)
                boxes.append((cx, cy))
        elif etype == "ARC":
            boxes.append((entity.dxf.center.x, entity.dxf.center.y))

    if not boxes:
        return DEFAULT_VIEWS

    # 간단한 gap 기반 클러스터링
    pts = sorted(boxes, key=lambda p: p[0])
    clusters = []
    current = [pts[0]]
    for p in pts[1:]:
        if p[0] - current[-1][0] > 20:
            clusters.append(current)
            current = [p]
        else:
            current.append(p)
    clusters.append(current)

    if len(clusters) < 4:
        return DEFAULT_VIEWS

    views = {}
    labels = [
        ("view1_plan", "View 1 - Plan (평면도)"),
        ("view2_elevation_front", "View 2 - Front Elevation (정면도)"),
        ("view3_elevation_side", "View 3 - Side Elevation (측면도)"),
        ("view4_isometric", "View 4 - Isometric (등각 투영도)"),
    ]

    for i, (name, label) in enumerate(labels):
        if i < len(clusters):
            xs = [p[0] for p in clusters[i]]
            ys = [p[1] for p in clusters[i]]
            views[name] = {
                "label": label,
                "xmin": min(xs) - MARGIN, "xmax": max(xs) + MARGIN,
                "ymin": min(ys) - MARGIN, "ymax": max(ys) + MARGIN,
            }
    return views if len(views) == 4 else DEFAULT_VIEWS


def render_full(dxf_path: str, output_dir: str, dpi: int = 300) -> str:
    """전체 DXF를 PNG로 렌더링"""
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    fig = plt.figure(figsize=(20, 12))
    ax = fig.add_axes([0, 0, 1, 1])
    ctx = RenderContext(doc)
    out = MatplotlibBackend(ax)
    Frontend(ctx, out).draw_layout(msp)
    ax.set_aspect("equal")

    out_path = Path(output_dir) / "dxf_full.png"
    fig.savefig(str(out_path), dpi=dpi, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    plt.close(fig)
    logger.info(f"Full render: {out_path}")
    return str(out_path)


def render_views(dxf_path: str, output_dir: str, dpi: int = 300) -> list[str]:
    """4개 뷰를 각각 PNG로 렌더링"""
    doc = ezdxf.readfile(dxf_path)
    views = _detect_views(doc)
    results = []

    for name, info in views.items():
        msp = doc.modelspace()
        width = info["xmax"] - info["xmin"]
        height = info["ymax"] - info["ymin"]
        aspect = width / max(height, 0.01)

        fig_h = max(8, 10)
        fig_w = max(10, fig_h * aspect)

        fig, ax = plt.subplots(figsize=(fig_w, fig_h))
        ctx = RenderContext(doc)
        out = MatplotlibBackend(ax)
        Frontend(ctx, out).draw_layout(msp)

        ax.set_xlim(info["xmin"], info["xmax"])
        ax.set_ylim(info["ymin"], info["ymax"])
        ax.set_aspect("equal")
        ax.set_title(info["label"], fontsize=16, fontweight="bold", pad=15)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)

        out_path = Path(output_dir) / f"{name}.png"
        fig.savefig(str(out_path), dpi=dpi, bbox_inches="tight",
                    facecolor="white", edgecolor="none", pad_inches=0.3)
        plt.close(fig)
        results.append(str(out_path))
        logger.info(f"View render: {out_path}")

    return results


def _get_entities_data(doc):
    """뷰별 엔티티 데이터 수집"""
    msp = doc.modelspace()
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

    return lines_by_view, polys_by_view


def _find_major_grids(lines, polys, min_length=10.0):
    """주요 그리드라인 좌표 추출"""
    h_lines = []
    v_lines = []
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

    return cluster([l[0] for l in h_lines], tol=0.5), cluster([l[0] for l in v_lines], tol=0.5)


def _add_dim_annotation(ax, p1, p2, offset, direction, color="#FF4444", fontsize=7):
    """치수선 주석 추가"""
    if direction == "h":
        x1, x2 = p1[0], p2[0]
        y = p1[1] + offset
        dist_mm = to_mm(abs(x2 - x1))
        ax.plot([x1, x1], [p1[1], y], color=color, linewidth=0.3, alpha=0.6)
        ax.plot([x2, x2], [p2[1], y], color=color, linewidth=0.3, alpha=0.6)
        ax.annotate("", xy=(x2, y), xytext=(x1, y),
                     arrowprops=dict(arrowstyle="<->", color=color, lw=0.6))
        ax.text((x1 + x2) / 2, y + offset * 0.15, f"{dist_mm:.0f}",
                ha="center", va="bottom" if offset > 0 else "top",
                fontsize=fontsize, color=color, fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.1", facecolor="white", edgecolor="none", alpha=0.85))
    elif direction == "v":
        y1, y2 = p1[1], p2[1]
        x = p1[0] + offset
        dist_mm = to_mm(abs(y2 - y1))
        ax.plot([p1[0], x], [y1, y1], color=color, linewidth=0.3, alpha=0.6)
        ax.plot([p2[0], x], [y2, y2], color=color, linewidth=0.3, alpha=0.6)
        ax.annotate("", xy=(x, y2), xytext=(x, y1),
                     arrowprops=dict(arrowstyle="<->", color=color, lw=0.6))
        ax.text(x + offset * 0.15, (y1 + y2) / 2, f"{dist_mm:.0f}",
                ha="left" if offset > 0 else "right", va="center",
                fontsize=fontsize, color=color, fontweight="bold", rotation=90,
                bbox=dict(boxstyle="round,pad=0.1", facecolor="white", edgecolor="none", alpha=0.85))


def render_2d_drawing(dxf_path: str, output_dir: str, dpi: int = 300) -> list[str]:
    """2D 도면 파일 생성 - 세부 치수 역계산 포함 (PIPE BOM 수준의 상세 도면)"""
    doc = ezdxf.readfile(dxf_path)
    lines_by_view, polys_by_view = _get_entities_data(doc)
    results = []

    view_configs = {
        "plan": {
            "bounds": VIEW_BOUNDS["plan"],
            "filename": "drawing_plan_dims.png",
            "title": "Plan View (평면도) - Detailed Dimensions (mm)",
        },
        "front": {
            "bounds": VIEW_BOUNDS["front"],
            "filename": "drawing_front_dims.png",
            "title": "Front Elevation (정면도) - Detailed Dimensions (mm)",
        },
        "side": {
            "bounds": VIEW_BOUNDS["side"],
            "filename": "drawing_side_dims.png",
            "title": "Side Elevation (측면도) - Detailed Dimensions (mm)",
        },
        "iso": {
            "bounds": VIEW_BOUNDS["iso"],
            "filename": "drawing_iso_dims.png",
            "title": "Isometric View (등각 투영도) - Dimensions (mm)",
        },
    }

    for view_name, config in view_configs.items():
        msp = doc.modelspace()
        bounds = config["bounds"]
        lines = lines_by_view.get(view_name, [])
        polys = polys_by_view.get(view_name, [])

        margin = 8
        xmin = bounds["xmin"] + margin
        xmax = bounds["xmax"] - margin
        ymin = bounds["ymin"] + margin
        ymax = bounds["ymax"] - margin
        width = xmax - xmin
        height = ymax - ymin
        aspect = width / max(height, 0.01)

        fig_h = max(10, 12)
        fig_w = max(12, fig_h * aspect)
        fig, ax = plt.subplots(figsize=(fig_w, fig_h))

        ctx = RenderContext(doc)
        out = MatplotlibBackend(ax)
        Frontend(ctx, out).draw_layout(msp)

        pad_x = width * 0.15
        pad_y = height * 0.15
        ax.set_xlim(xmin - pad_x, xmax + pad_x)
        ax.set_ylim(ymin - pad_y, ymax + pad_y)
        ax.set_aspect("equal")

        # 역계산 치수 자동 추가
        h_ys, v_xs = _find_major_grids(lines, polys, min_length=5.0)

        # 전체 범위 치수
        if lines or polys:
            all_x, all_y = [], []
            for (x1, y1), (x2, y2) in lines:
                all_x.extend([x1, x2])
                all_y.extend([y1, y2])
            for pts in polys:
                for x, y in pts:
                    all_x.append(x)
                    all_y.append(y)

            if all_x and all_y:
                ext_xmin, ext_xmax = min(all_x), max(all_x)
                ext_ymin, ext_ymax = min(all_y), max(all_y)

                # 전체 가로 (상단)
                _add_dim_annotation(ax, (ext_xmin, ext_ymax), (ext_xmax, ext_ymax),
                                    offset=pad_y * 0.5, direction="h", color="#FF2222", fontsize=9)
                # 전체 세로 (좌측)
                _add_dim_annotation(ax, (ext_xmin, ext_ymin), (ext_xmin, ext_ymax),
                                    offset=-pad_x * 0.5, direction="v", color="#FF2222", fontsize=9)

        # 주요 그리드 간격 치수 (우측)
        if len(h_ys) >= 2:
            for i in range(1, min(len(h_ys), 15)):
                gap_mm = to_mm(h_ys[i] - h_ys[i-1])
                if gap_mm > 200:
                    x_pos = (xmax if all_x else bounds["xmax"]) if lines or polys else bounds["xmax"]
                    _add_dim_annotation(ax, (x_pos, h_ys[i-1]), (x_pos, h_ys[i]),
                                        offset=pad_x * 0.3, direction="v",
                                        color="#2288FF", fontsize=7)

        # 주요 수직 그리드 간격 (하단)
        if len(v_xs) >= 2:
            for i in range(1, min(len(v_xs), 15)):
                gap_mm = to_mm(v_xs[i] - v_xs[i-1])
                if gap_mm > 200:
                    y_pos = (ymin if all_y else bounds["ymin"]) if lines or polys else bounds["ymin"]
                    _add_dim_annotation(ax, (v_xs[i-1], y_pos), (v_xs[i], y_pos),
                                        offset=-pad_y * 0.3, direction="h",
                                        color="#2288FF", fontsize=7)

        # 부재 사각형 치수 (Plan 뷰만)
        if view_name == "plan":
            rectangles = []
            for pts in polys:
                n = len(pts)
                if n in (4, 5):
                    xs = [p[0] for p in pts[:4]]
                    ys = [p[1] for p in pts[:4]]
                    w = max(xs) - min(xs)
                    h = max(ys) - min(ys)
                    w_mm, h_mm = to_mm(w), to_mm(h)
                    if 30 < w_mm < 600 and 30 < h_mm < 600:
                        rectangles.append({
                            "xmin": min(xs), "xmax": max(xs),
                            "ymin": min(ys), "ymax": max(ys),
                            "w_mm": w_mm, "h_mm": h_mm,
                        })

            # 주요 부재(50mm 이상)에 크기 라벨 추가
            shown = 0
            for r in sorted(rectangles, key=lambda r: r["w_mm"] * r["h_mm"], reverse=True):
                if shown >= 20:
                    break
                if r["w_mm"] > 80 and r["h_mm"] > 80:
                    cx = (r["xmin"] + r["xmax"]) / 2
                    cy = (r["ymin"] + r["ymax"]) / 2
                    ax.text(cx, cy, f"{r['w_mm']:.0f}x{r['h_mm']:.0f}",
                            ha="center", va="center", fontsize=5, color="#884400",
                            bbox=dict(boxstyle="round,pad=0.1", facecolor="lightyellow",
                                      edgecolor="#CCAA00", alpha=0.8))
                    shown += 1

        ax.set_title(config["title"], fontsize=14, fontweight="bold", pad=15)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.text(0.02, 0.02, f"Scale: 1 unit = {DIMLFAC:.1f} mm | DIMLFAC = {DIMLFAC}",
                transform=ax.transAxes, fontsize=8, color="gray", verticalalignment="bottom")

        out_path = Path(output_dir) / config["filename"]
        fig.savefig(str(out_path), dpi=dpi, bbox_inches="tight",
                    facecolor="white", edgecolor="none", pad_inches=0.3)
        plt.close(fig)
        results.append(str(out_path))
        logger.info(f"2D drawing: {out_path}")

    return results


def analyze_dimensions(dxf_path: str) -> dict:
    """DXF 치수 역산 분석 결과를 JSON으로 반환"""
    doc = ezdxf.readfile(dxf_path)
    lines_by_view, polys_by_view = _get_entities_data(doc)

    result = {"dimlfac": DIMLFAC, "views": {}}

    for view_name, bounds in VIEW_BOUNDS.items():
        lines = lines_by_view.get(view_name, [])
        polys = polys_by_view.get(view_name, [])
        h_ys, v_xs = _find_major_grids(lines, polys, min_length=10.0)

        all_x, all_y = [], []
        for (x1, y1), (x2, y2) in lines:
            all_x.extend([x1, x2])
            all_y.extend([y1, y2])
        for pts in polys:
            for x, y in pts:
                all_x.append(x)
                all_y.append(y)

        view_data = {
            "entity_count": len(lines) + len(polys),
            "overall_width_mm": round(to_mm(max(all_x) - min(all_x)), 0) if all_x else 0,
            "overall_height_mm": round(to_mm(max(all_y) - min(all_y)), 0) if all_y else 0,
            "h_grid_spacings_mm": [],
            "v_grid_spacings_mm": [],
        }

        for i in range(1, len(h_ys)):
            gap_mm = round(to_mm(h_ys[i] - h_ys[i-1]), 0)
            if gap_mm > 100:
                view_data["h_grid_spacings_mm"].append(gap_mm)

        for i in range(1, len(v_xs)):
            gap_mm = round(to_mm(v_xs[i] - v_xs[i-1]), 0)
            if gap_mm > 100:
                view_data["v_grid_spacings_mm"].append(gap_mm)

        # 부재 분석 (Plan 뷰만)
        if view_name == "plan":
            rectangles = []
            for pts in polys:
                n = len(pts)
                if n in (4, 5):
                    xs = [p[0] for p in pts[:4]]
                    ys = [p[1] for p in pts[:4]]
                    w, h = max(xs) - min(xs), max(ys) - min(ys)
                    if to_mm(w) > 30 and to_mm(h) > 30:
                        rectangles.append({"w_mm": round(to_mm(w)), "h_mm": round(to_mm(h))})
            view_data["detected_members"] = len(rectangles)
            # 크기별 그룹핑
            size_groups = defaultdict(int)
            for r in rectangles:
                w_r = round(r["w_mm"] / 10) * 10
                h_r = round(r["h_mm"] / 10) * 10
                key = f"{min(w_r, h_r)}x{max(w_r, h_r)}"
                size_groups[key] += 1
            view_data["member_sizes"] = dict(sorted(size_groups.items(), key=lambda x: -x[1]))

        result["views"][view_name] = view_data

    return result


def process_dxf(dxf_path: str, output_dir: str) -> dict:
    """전체 DXF 처리 파이프라인"""
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    full_png = render_full(dxf_path, output_dir)
    view_pngs = render_views(dxf_path, output_dir)
    drawing_pngs = render_2d_drawing(dxf_path, output_dir)
    dimensions = analyze_dimensions(dxf_path)

    # 치수 분석 JSON 저장
    dim_path = Path(output_dir) / "dimensions.json"
    with open(dim_path, "w") as f:
        json.dump(dimensions, f, indent=2, ensure_ascii=False)

    return {
        "full_render": full_png,
        "view_renders": view_pngs,
        "drawing_renders": drawing_pngs,
        "dimensions": dimensions,
        "dimensions_json": str(dim_path),
        "files": [full_png] + view_pngs + drawing_pngs + [str(dim_path)],
    }
