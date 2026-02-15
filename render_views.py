#!/usr/bin/env python3
"""DXF 파일의 4개 뷰를 각각 개별 이미지로 렌더링 (치수 포함)"""
import ezdxf
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
import matplotlib.pyplot as plt
from pathlib import Path

DXF_PATH = Path(__file__).parent / "1. 260210-AI-SAMPLE.dxf"
OUTPUT_DIR = Path(__file__).parent

# 클러스터 분석 결과로부터 4개 뷰 영역 정의 (margin 포함)
MARGIN = 5  # 여백
VIEWS = {
    "view1_plan": {
        "label": "View 1 - Plan (평면도)",
        "xmin": -10016.83 - MARGIN, "xmax": -9924.67 + MARGIN,
        "ymin": 3148.17 - MARGIN,  "ymax": 3211.66 + MARGIN,
    },
    "view2_elevation_front": {
        "label": "View 2 - Front Elevation (정면도)",
        "xmin": -9902.00 - MARGIN, "xmax": -9808.95 + MARGIN,
        "ymin": 3169.80 - MARGIN,  "ymax": 3184.06 + MARGIN,
    },
    "view3_elevation_side": {
        "label": "View 3 - Side Elevation (측면도)",
        "xmin": -9779.52 - MARGIN, "xmax": -9722.00 + MARGIN,
        "ymin": 3169.80 - MARGIN,  "ymax": 3184.06 + MARGIN,
    },
    "view4_isometric": {
        "label": "View 4 - Isometric (등각 투영도)",
        "xmin": -9909.30 - MARGIN, "xmax": -9808.99 + MARGIN,
        "ymin": 3060.29 - MARGIN,  "ymax": 3122.52 + MARGIN,
    },
}


def render_view(view_name, view_info, dpi=300):
    """특정 뷰 영역만 크롭하여 PNG로 렌더링"""
    doc = ezdxf.readfile(str(DXF_PATH))
    msp = doc.modelspace()

    # 뷰의 가로/세로 비율 계산
    width = view_info["xmax"] - view_info["xmin"]
    height = view_info["ymax"] - view_info["ymin"]
    aspect = width / height

    # 적절한 figure 크기 (최소 높이 8인치)
    fig_h = max(8, 10)
    fig_w = fig_h * aspect
    if fig_w < 10:
        fig_w = 10
        fig_h = fig_w / aspect

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))

    ctx = RenderContext(doc)
    out = MatplotlibBackend(ax)
    Frontend(ctx, out).draw_layout(msp)

    # 뷰 영역으로 줌
    ax.set_xlim(view_info["xmin"], view_info["xmax"])
    ax.set_ylim(view_info["ymin"], view_info["ymax"])
    ax.set_aspect("equal")

    # 타이틀 추가
    ax.set_title(view_info["label"], fontsize=16, fontweight="bold", pad=15)

    # 축 눈금 제거 (깔끔한 도면 이미지)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    # 저장
    png_path = OUTPUT_DIR / f"{view_name}.png"
    fig.savefig(str(png_path), dpi=dpi, bbox_inches="tight",
                facecolor="white", edgecolor="none", pad_inches=0.3)
    plt.close(fig)
    print(f"  Saved: {png_path.name} ({png_path.stat().st_size / 1024:.0f} KB)")
    return png_path


if __name__ == "__main__":
    print("=== 4개 뷰 개별 렌더링 시작 ===\n")

    for name, info in VIEWS.items():
        print(f"Rendering {info['label']}...")
        render_view(name, info)

    print("\n=== 완료 ===")
