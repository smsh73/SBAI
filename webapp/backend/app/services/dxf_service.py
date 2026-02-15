"""DXF 렌더링 & 분석 서비스"""
import ezdxf
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.lines as mlines
import matplotlib.collections as mcoll
import matplotlib.patches as mpatches
import matplotlib.text as mtext
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
from pathlib import Path
from collections import defaultdict
import logging
import json

logger = logging.getLogger(__name__)

DIMLFAC = 75.01875305175781
MARGIN = 5

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


def _cluster_values(values, tol=0.4):
    """근접 값 클러스터링"""
    if not values:
        return []
    sv = sorted(values)
    groups = [[sv[0]]]
    for v in sv[1:]:
        if v - groups[-1][-1] < tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    return sorted([np.mean(g) for g in groups])


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


def render_full(doc, output_dir: str, dpi: int = 300) -> str:
    """전체 DXF를 PNG로 렌더링"""
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


def render_views(doc, output_dir: str, dpi: int = 300) -> list[str]:
    """4개 뷰를 각각 PNG로 렌더링 - 1회 렌더링 후 뷰 영역 크롭"""
    views = _detect_views(doc)
    msp = doc.modelspace()
    results = []

    fig = plt.figure(figsize=(20, 12))
    ax = fig.add_axes([0, 0, 1, 1])
    ctx = RenderContext(doc)
    out = MatplotlibBackend(ax)
    Frontend(ctx, out).draw_layout(msp)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    for name, info in views.items():
        ax.set_xlim(info["xmin"], info["xmax"])
        ax.set_ylim(info["ymin"], info["ymax"])
        ax.set_aspect("equal")

        out_path = Path(output_dir) / f"{name}.png"
        fig.savefig(str(out_path), dpi=dpi, bbox_inches="tight",
                    facecolor="white", edgecolor="none", pad_inches=0.3)
        results.append(str(out_path))
        logger.info(f"View render: {out_path}")

    plt.close(fig)
    return results


# ─── 2D 도면 관련 함수들 ───────────────────────────────────────

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


def _force_bw(ax):
    """모든 DXF 렌더링 요소를 흑백(검정 선, 흰 배경)으로 변환"""
    for child in list(ax.get_children()):
        if child is ax.patch:
            continue
        try:
            if isinstance(child, mlines.Line2D):
                child.set_color('#000000')
                child.set_linewidth(max(0.07, min(child.get_linewidth(), 0.25)))
            elif isinstance(child, mcoll.LineCollection):
                child.set_colors(['#000000'])
                lws = child.get_linewidths()
                child.set_linewidths([max(0.07, min(lw, 0.25)) for lw in lws])
            elif isinstance(child, (mcoll.PathCollection, mcoll.PatchCollection)):
                child.set_edgecolors('#000000')
                child.set_facecolors('none')
            elif isinstance(child, mcoll.Collection):
                child.set_edgecolors('#000000')
                child.set_facecolors('none')
            elif isinstance(child, mpatches.Patch):
                child.set_edgecolor('#000000')
                child.set_facecolor('none')
            elif isinstance(child, mtext.Text):
                child.set_color('#000000')
        except Exception:
            pass


def _get_boundary_positions(lines, polys, min_seg_len=0.3, cluster_tol=0.4):
    """경계선 위치 추출 - 모든 H/V 세그먼트의 위치와 끝점을 수집"""
    segs = []
    for (x1, y1), (x2, y2) in lines:
        segs.append((x1, y1, x2, y2))
    for pts in polys:
        for i in range(len(pts) - 1):
            segs.append((pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1]))

    v_xs = []
    h_ys = []

    for x1, y1, x2, y2 in segs:
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        length = (dx**2 + dy**2) ** 0.5
        if length < min_seg_len:
            continue

        if dy < 0.2:
            h_ys.append((y1 + y2) / 2)
            v_xs.append(min(x1, x2))
            v_xs.append(max(x1, x2))
        elif dx < 0.2:
            v_xs.append((x1 + x2) / 2)
            h_ys.append(min(y1, y2))
            h_ys.append(max(y1, y2))

    return _cluster_values(h_ys, cluster_tol), _cluster_values(v_xs, cluster_tol)


# ─── 세그먼트 평행 치수 (PIPE BOM 스타일) ─────────────────────

def _collect_unique_segments(lines, polys, min_len_mm=80):
    """유의미한 고유 세그먼트 수집 - 중복 제거, 외곽 우선"""
    raw = []
    for (x1, y1), (x2, y2) in lines:
        raw.append((x1, y1, x2, y2))
    for pts in polys:
        for i in range(len(pts) - 1):
            raw.append((pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1]))

    # 길이 필터 + 방향 정규화 (항상 왼→오, 같으면 아래→위)
    filtered = []
    for x1, y1, x2, y2 in raw:
        length = ((x2 - x1)**2 + (y2 - y1)**2)**0.5
        length_mm = length * DIMLFAC
        if length_mm < min_len_mm:
            continue
        # 방향 정규화
        if x1 > x2 + 0.01 or (abs(x1 - x2) < 0.01 and y1 > y2):
            x1, y1, x2, y2 = x2, y2, x1, y1
        filtered.append((x1, y1, x2, y2, length_mm))

    if not filtered:
        return []

    # 전체 중심점 계산 (외곽 방향 결정용)
    all_x = []
    all_y = []
    for x1, y1, x2, y2, _ in filtered:
        all_x.extend([x1, x2])
        all_y.extend([y1, y2])
    cx = np.mean(all_x)
    cy = np.mean(all_y)

    # 중복 제거: 같은 방향 + 가까운 평행 세그먼트 → 외곽 쪽 유지
    used = set()
    unique = []

    for i in range(len(filtered)):
        if i in used:
            continue
        x1, y1, x2, y2, l = filtered[i]
        seg_len = ((x2 - x1)**2 + (y2 - y1)**2)**0.5
        angle = np.arctan2(y2 - y1, x2 - x1)
        mid = ((x1 + x2) / 2, (y1 + y2) / 2)

        # 이 세그먼트와 유사한 것들을 그룹화
        group = [(x1, y1, x2, y2, l, mid)]

        for j in range(i + 1, len(filtered)):
            if j in used:
                continue
            bx1, by1, bx2, by2, bl = filtered[j]
            bangle = np.arctan2(by2 - by1, bx2 - bx1)

            # 각도 차이 검사
            angle_diff = abs(angle - bangle)
            if angle_diff > np.pi:
                angle_diff = 2 * np.pi - angle_diff
            if angle_diff > np.radians(5):
                continue

            # 수직 거리 계산
            if seg_len > 0.001:
                bmid = ((bx1 + bx2) / 2, (by1 + by2) / 2)
                perp_dist = abs((x2 - x1) * (y1 - bmid[1]) - (x1 - bmid[0]) * (y2 - y1)) / seg_len
            else:
                continue

            # 길이 유사성 검사 (70% 이상 유사)
            len_ratio = min(l, bl) / max(l, bl) if max(l, bl) > 0 else 0

            # 가까운 평행 세그먼트 (400mm 이내) + 유사한 길이 → 같은 부재의 양면
            if perp_dist * DIMLFAC < 400 and len_ratio > 0.7:
                used.add(j)
                group.append((bx1, by1, bx2, by2, bl, bmid))

        # 그룹 내에서 중심에서 가장 먼 세그먼트 선택 (외곽)
        best = max(group, key=lambda s:
            ((s[5][0] - cx)**2 + (s[5][1] - cy)**2)**0.5)
        unique.append(best[:5])
        used.add(i)

    return unique


def _add_segment_parallel_dims(ax, segments, center_x, center_y):
    """각 세그먼트에 평행한 치수를 도형 외곽에 표시 (PIPE BOM 스타일)

    - 연장선: 세그먼트 끝점에서 외곽 방향으로 수직
    - 치수선: 세그먼트와 평행, 외곽 오프셋
    - 텍스트: 세그먼트 방향으로 회전, 가독성 확보
    - 충돌 감지: 텍스트가 겹치지 않도록 최소 거리 검사
    """
    artists = []
    placed_texts = []  # (x, y) 이미 배치된 텍스트 중심점
    DIM_C = '#555555'
    EXT_LW = 0.15
    DIM_LW = 0.2
    FS = 5.5

    # 밀도 기반 충돌 거리 조정 + 긴 세그먼트 우선 배치
    if len(segments) > 30:
        MIN_TEXT_DIST = 4.0
    elif len(segments) > 15:
        MIN_TEXT_DIST = 2.8
    else:
        MIN_TEXT_DIST = 1.8
    SAME_VAL_MULT = 2.5  # 같은 수치값이면 더 먼 거리 요구

    segments_sorted = sorted(segments, key=lambda s: s[4], reverse=True)

    for x1, y1, x2, y2, length_mm in segments_sorted:
        dx = x2 - x1
        dy = y2 - y1
        seg_len = (dx**2 + dy**2)**0.5
        if seg_len < 0.001:
            continue

        angle = np.arctan2(dy, dx)

        # 수직 단위 벡터 (2가지 방향)
        perp_x = -np.sin(angle)
        perp_y = np.cos(angle)

        # 외곽 방향 선택 (중심에서 반대 방향)
        mid_x = (x1 + x2) / 2
        mid_y = (y1 + y2) / 2
        to_center_x = center_x - mid_x
        to_center_y = center_y - mid_y

        if perp_x * to_center_x + perp_y * to_center_y > 0:
            perp_x = -perp_x
            perp_y = -perp_y

        # 오프셋 거리 (도형에서 충분히 떨어지도록)
        offset = max(seg_len * 0.12, 2.0)
        offset = min(offset, 6.0)

        # 텍스트 위치 사전 계산 (충돌 검사용)
        dim_x1 = x1 + perp_x * offset
        dim_y1 = y1 + perp_y * offset
        dim_x2 = x2 + perp_x * offset
        dim_y2 = y2 + perp_y * offset
        text_x = (dim_x1 + dim_x2) / 2 + perp_x * offset * 0.3
        text_y = (dim_y1 + dim_y2) / 2 + perp_y * offset * 0.3

        # 충돌 감지: 이미 배치된 텍스트와 너무 가까우면 건너뜀
        # 같은 수치값이면 더 먼 거리 요구 (양면 중복 방지)
        too_close = False
        for px, py, pval in placed_texts:
            dist = ((text_x - px)**2 + (text_y - py)**2)**0.5
            check_dist = MIN_TEXT_DIST * SAME_VAL_MULT if abs(pval - length_mm) < 1 else MIN_TEXT_DIST
            if dist < check_dist:
                too_close = True
                break
        if too_close:
            continue
        placed_texts.append((text_x, text_y, length_mm))

        ext_len = offset * 1.2

        # 연장선 1 (끝점 1에서 외곽 방향)
        a = ax.plot([x1, x1 + perp_x * ext_len],
                    [y1, y1 + perp_y * ext_len],
                    color=DIM_C, lw=EXT_LW, alpha=0.4)
        artists.append(a[0])

        # 연장선 2 (끝점 2에서 외곽 방향)
        a = ax.plot([x2, x2 + perp_x * ext_len],
                    [y2, y2 + perp_y * ext_len],
                    color=DIM_C, lw=EXT_LW, alpha=0.4)
        artists.append(a[0])

        # 치수선 (세그먼트와 평행, 오프셋 위치)
        a = ax.annotate('', xy=(dim_x2, dim_y2), xytext=(dim_x1, dim_y1),
                        arrowprops=dict(arrowstyle='<->', color=DIM_C, lw=DIM_LW))
        artists.append(a)

        # 텍스트 각도 (가독성: -90~90도 범위)
        text_angle = np.degrees(angle)
        if text_angle > 90:
            text_angle -= 180
        elif text_angle < -90:
            text_angle += 180

        a = ax.text(text_x, text_y, f'{length_mm:.0f}',
                    ha='center', va='center',
                    fontsize=FS, color=DIM_C, fontweight='bold',
                    rotation=text_angle, rotation_mode='anchor',
                    bbox=dict(boxstyle='round,pad=0.15', fc='white', ec='none', alpha=0.95))
        artists.append(a)

    return artists


def _add_overall_dims(ax, segments):
    """전체 폭/높이 치수 추가 (하단 + 우측, 빨간색)"""
    if not segments:
        return []

    artists = []
    all_x = []
    all_y = []
    for x1, y1, x2, y2, _ in segments:
        all_x.extend([x1, x2])
        all_y.extend([y1, y2])

    xmin, xmax = min(all_x), max(all_x)
    ymin, ymax = min(all_y), max(all_y)
    w = xmax - xmin
    h = ymax - ymin

    OVR_C = '#CC0000'
    EXT_LW = 0.15
    FS = 6.5

    # 하단: 전체 폭
    if w * DIMLFAC > 30:
        step = max(h * 0.10, 1.5)
        y_dim = ymin - step * 3.0
        for x in [xmin, xmax]:
            artists.append(ax.plot([x, x], [ymin, y_dim - step * 0.3],
                                   color=OVR_C, lw=EXT_LW, alpha=0.4)[0])
        artists.append(ax.annotate('', xy=(xmax, y_dim), xytext=(xmin, y_dim),
                                   arrowprops=dict(arrowstyle='<->', color=OVR_C, lw=0.35)))
        artists.append(ax.text((xmin + xmax) / 2, y_dim - step * 0.35, f'{w * DIMLFAC:.0f}',
                               ha='center', va='top', fontsize=FS, color=OVR_C, fontweight='bold',
                               bbox=dict(boxstyle='round,pad=0.1', fc='white', ec=OVR_C, lw=0.3, alpha=0.95)))

    # 우측: 전체 높이
    if h * DIMLFAC > 30:
        step = max(w * 0.10, 1.5)
        x_dim = xmax + step * 3.0
        for y in [ymin, ymax]:
            artists.append(ax.plot([xmax, x_dim + step * 0.3], [y, y],
                                   color=OVR_C, lw=EXT_LW, alpha=0.4)[0])
        artists.append(ax.annotate('', xy=(x_dim, ymax), xytext=(x_dim, ymin),
                                   arrowprops=dict(arrowstyle='<->', color=OVR_C, lw=0.35)))
        artists.append(ax.text(x_dim + step * 0.35, (ymin + ymax) / 2, f'{h * DIMLFAC:.0f}',
                               ha='left', va='center', fontsize=FS, color=OVR_C, fontweight='bold',
                               rotation=90,
                               bbox=dict(boxstyle='round,pad=0.1', fc='white', ec=OVR_C, lw=0.3, alpha=0.95)))

    return artists


def render_2d_drawing(doc, output_dir: str, dpi: int = 300) -> list[str]:
    """2D 도면 생성 - 흰 배경 검정 선 + 세그먼트 평행 치수 (PIPE BOM 스타일)"""
    lines_by_view, polys_by_view = _get_entities_data(doc)
    msp = doc.modelspace()
    results = []

    view_configs = {
        "plan": {
            "bounds": VIEW_BOUNDS["plan"],
            "filename": "drawing_plan_dims.png",
            "title": "Plan View - Dimensions (mm)",
        },
        "front": {
            "bounds": VIEW_BOUNDS["front"],
            "filename": "drawing_front_dims.png",
            "title": "Front Elevation - Dimensions (mm)",
        },
        "side": {
            "bounds": VIEW_BOUNDS["side"],
            "filename": "drawing_side_dims.png",
            "title": "Side Elevation - Dimensions (mm)",
        },
        "iso": {
            "bounds": VIEW_BOUNDS["iso"],
            "filename": "drawing_iso_dims.png",
            "title": "Isometric View - Dimensions (mm)",
        },
    }

    # 한 번만 렌더링
    fig, ax = plt.subplots(figsize=(20, 16))
    ctx = RenderContext(doc)
    out = MatplotlibBackend(ax)
    Frontend(ctx, out).draw_layout(msp)

    # B&W 변환 + 불투명 흰색 배경
    _force_bw(ax)
    fig.patch.set_facecolor('white')
    fig.patch.set_alpha(1.0)
    ax.set_facecolor('white')
    ax.patch.set_facecolor('white')
    ax.patch.set_alpha(1.0)

    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    for view_name, config in view_configs.items():
        bounds = config["bounds"]
        lines = lines_by_view.get(view_name, [])
        polys = polys_by_view.get(view_name, [])
        added = []

        # 고유 세그먼트 수집
        segments = _collect_unique_segments(lines, polys)

        if segments:
            all_xs = []
            all_ys = []
            for sx1, sy1, sx2, sy2, _ in segments:
                all_xs.extend([sx1, sx2])
                all_ys.extend([sy1, sy2])
            center_x = np.mean(all_xs)
            center_y = np.mean(all_ys)
            ent_xmin, ent_xmax = min(all_xs), max(all_xs)
            ent_ymin, ent_ymax = min(all_ys), max(all_ys)
        else:
            center_x = (bounds["xmin"] + bounds["xmax"]) / 2
            center_y = (bounds["ymin"] + bounds["ymax"]) / 2
            ent_xmin = bounds["xmin"] + 10
            ent_xmax = bounds["xmax"] - 10
            ent_ymin = bounds["ymin"] + 10
            ent_ymax = bounds["ymax"] - 10

        # 세그먼트 평행 치수 추가
        added += _add_segment_parallel_dims(ax, segments, center_x, center_y)

        # 전체 치수 추가 (하단/우측, 빨간색)
        added += _add_overall_dims(ax, segments)

        ew = max(ent_xmax - ent_xmin, 0.01)
        eh = max(ent_ymax - ent_ymin, 0.01)

        # 균일한 패딩 (치수 표시 공간 확보 - 오프셋 증가분 반영)
        pad = max(ew, eh) * 0.3
        pad = max(pad, 8.0)
        ax.set_xlim(ent_xmin - pad, ent_xmax + pad)
        ax.set_ylim(ent_ymin - pad, ent_ymax + pad)
        ax.set_aspect("equal")

        # 타이틀 & 스케일
        title_a = ax.set_title(config["title"], fontsize=13, fontweight="bold", pad=12, color='#333333')
        scale_a = ax.text(0.02, 0.01,
                          f"DIMLFAC = {DIMLFAC:.2f} | 1 unit = {DIMLFAC:.1f} mm",
                          transform=ax.transAxes, fontsize=7, color="#888888",
                          verticalalignment="bottom")
        added.extend([title_a, scale_a])

        out_path = Path(output_dir) / config["filename"]
        fig.savefig(str(out_path), dpi=dpi, bbox_inches="tight",
                    facecolor="white", edgecolor="none", pad_inches=0.3)
        results.append(str(out_path))
        logger.info(f"2D drawing: {out_path}")

        # 다음 뷰를 위해 주석 제거
        for a in added:
            try:
                a.remove()
            except Exception:
                pass

    plt.close(fig)
    return results


# ─── 치수 분석 ───────────────────────────────────────────

def analyze_dimensions(doc) -> dict:
    """DXF 치수 역산 분석 결과를 JSON으로 반환"""
    lines_by_view, polys_by_view = _get_entities_data(doc)

    result = {"dimlfac": DIMLFAC, "views": {}}

    for view_name, bounds in VIEW_BOUNDS.items():
        lines = lines_by_view.get(view_name, [])
        polys = polys_by_view.get(view_name, [])
        h_ys, v_xs = _get_boundary_positions(lines, polys)

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
            "h_boundary_count": len(h_ys),
            "v_boundary_count": len(v_xs),
            "h_spacings_mm": [round(to_mm(h_ys[i] - h_ys[i-1])) for i in range(1, len(h_ys))],
            "v_spacings_mm": [round(to_mm(v_xs[i] - v_xs[i-1])) for i in range(1, len(v_xs))],
        }

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

    doc = ezdxf.readfile(dxf_path)
    logger.info(f"DXF loaded: {dxf_path}")

    full_png = render_full(doc, output_dir)
    view_pngs = render_views(doc, output_dir)
    drawing_pngs = render_2d_drawing(doc, output_dir)
    dimensions = analyze_dimensions(doc)

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
