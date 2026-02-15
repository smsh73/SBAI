#!/usr/bin/env python3
"""DXF 파일 렌더링 및 변환 스크립트"""
import ezdxf
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
import matplotlib.pyplot as plt
from pathlib import Path

DXF_PATH = Path(__file__).parent / "1. 260210-AI-SAMPLE.dxf"
OUTPUT_DIR = Path(__file__).parent


def render_to_png(dpi=300):
    """DXF를 PNG 이미지로 렌더링"""
    doc = ezdxf.readfile(str(DXF_PATH))
    msp = doc.modelspace()

    fig = plt.figure(figsize=(20, 12))
    ax = fig.add_axes([0, 0, 1, 1])

    ctx = RenderContext(doc)
    out = MatplotlibBackend(ax)
    Frontend(ctx, out).draw_layout(msp)

    ax.set_aspect("equal")

    png_path = OUTPUT_DIR / "dxf_render.png"
    fig.savefig(str(png_path), dpi=dpi, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    plt.close(fig)
    print(f"PNG saved: {png_path}")
    return png_path


def render_to_svg():
    """DXF를 SVG로 변환"""
    doc = ezdxf.readfile(str(DXF_PATH))
    msp = doc.modelspace()

    fig = plt.figure(figsize=(20, 12))
    ax = fig.add_axes([0, 0, 1, 1])

    ctx = RenderContext(doc)
    out = MatplotlibBackend(ax)
    Frontend(ctx, out).draw_layout(msp)

    ax.set_aspect("equal")

    svg_path = OUTPUT_DIR / "dxf_render.svg"
    fig.savefig(str(svg_path), format="svg", bbox_inches="tight",
                facecolor="white", edgecolor="none")
    plt.close(fig)
    print(f"SVG saved: {svg_path}")
    return svg_path


if __name__ == "__main__":
    print("=== DXF 렌더링 시작 ===")
    print(f"입력 파일: {DXF_PATH}")

    png = render_to_png()
    svg = render_to_svg()

    print("\n=== 완료 ===")
    print(f"PNG: {png}")
    print(f"SVG: {svg}")
