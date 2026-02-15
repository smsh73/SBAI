#!/usr/bin/env python3
"""DXF 엔티티 좌표를 분석하여 뷰 영역을 식별"""
import ezdxf
from pathlib import Path
import json

DXF_PATH = Path(__file__).parent / "1. 260210-AI-SAMPLE.dxf"

doc = ezdxf.readfile(str(DXF_PATH))
msp = doc.modelspace()

# 모든 엔티티의 좌표를 수집
points = []
for entity in msp:
    etype = entity.dxftype()
    try:
        if etype == "LINE":
            s = entity.dxf.start
            e = entity.dxf.end
            points.append((s.x, s.y))
            points.append((e.x, e.y))
        elif etype == "LWPOLYLINE":
            for pt in entity.get_points(format="xy"):
                points.append(pt)
        elif etype == "ARC":
            c = entity.dxf.center
            r = entity.dxf.radius
            points.append((c.x - r, c.y - r))
            points.append((c.x + r, c.y + r))
        elif etype == "CIRCLE":
            c = entity.dxf.center
            r = entity.dxf.radius
            points.append((c.x - r, c.y - r))
            points.append((c.x + r, c.y + r))
        elif etype == "DIMENSION":
            if hasattr(entity.dxf, 'defpoint'):
                p = entity.dxf.defpoint
                points.append((p.x, p.y))
            if hasattr(entity.dxf, 'defpoint2'):
                p = entity.dxf.defpoint2
                points.append((p.x, p.y))
            if hasattr(entity.dxf, 'defpoint3'):
                p = entity.dxf.defpoint3
                points.append((p.x, p.y))
    except Exception as ex:
        pass

xs = [p[0] for p in points]
ys = [p[1] for p in points]

print(f"Total points: {len(points)}")
print(f"X range: {min(xs):.2f} ~ {max(xs):.2f}")
print(f"Y range: {min(ys):.2f} ~ {max(ys):.2f}")

# X, Y 히스토그램으로 클러스터 식별
import numpy as np

xs_arr = np.array(xs)
ys_arr = np.array(ys)

# X축 분포 확인 (빈도)
print("\n=== X축 분포 ===")
x_bins = np.histogram(xs_arr, bins=50)
for i, (count, edge) in enumerate(zip(x_bins[0], x_bins[1])):
    if count > 0:
        print(f"  X [{edge:.1f} ~ {x_bins[1][i+1]:.1f}]: {count} points")

print("\n=== Y축 분포 ===")
y_bins = np.histogram(ys_arr, bins=50)
for i, (count, edge) in enumerate(zip(y_bins[0], y_bins[1])):
    if count > 0:
        print(f"  Y [{edge:.1f} ~ {y_bins[1][i+1]:.1f}]: {count} points")

# 간격(gap)을 기반으로 클러스터링
from itertools import groupby

def find_clusters_1d(values, gap_threshold):
    """1D 값들을 gap 기준으로 클러스터링"""
    sorted_vals = sorted(set(values))
    clusters = []
    cluster = [sorted_vals[0]]
    for i in range(1, len(sorted_vals)):
        if sorted_vals[i] - sorted_vals[i-1] > gap_threshold:
            clusters.append((min(cluster), max(cluster)))
            cluster = [sorted_vals[i]]
        else:
            cluster.append(sorted_vals[i])
    clusters.append((min(cluster), max(cluster)))
    return clusters

# 포인트들을 그리드로 클러스터링
# 각 엔티티별로 바운딩박스 구하기
entity_boxes = []
for entity in msp:
    etype = entity.dxftype()
    ex, ey = [], []
    try:
        if etype == "LINE":
            s = entity.dxf.start
            e = entity.dxf.end
            ex = [s.x, e.x]; ey = [s.y, e.y]
        elif etype == "LWPOLYLINE":
            pts = list(entity.get_points(format="xy"))
            ex = [p[0] for p in pts]; ey = [p[1] for p in pts]
        elif etype == "ARC":
            c = entity.dxf.center; r = entity.dxf.radius
            ex = [c.x-r, c.x+r]; ey = [c.y-r, c.y+r]
        elif etype == "DIMENSION":
            if hasattr(entity.dxf, 'defpoint'):
                p = entity.dxf.defpoint; ex.append(p.x); ey.append(p.y)
            if hasattr(entity.dxf, 'defpoint2'):
                p = entity.dxf.defpoint2; ex.append(p.x); ey.append(p.y)
            if hasattr(entity.dxf, 'defpoint3'):
                p = entity.dxf.defpoint3; ex.append(p.x); ey.append(p.y)
    except:
        pass
    if ex and ey:
        cx = (min(ex) + max(ex)) / 2
        cy = (min(ey) + max(ey)) / 2
        entity_boxes.append({"cx": cx, "cy": cy,
                            "xmin": min(ex), "xmax": max(ex),
                            "ymin": min(ey), "ymax": max(ey)})

# 중심점으로 클러스터링
centers_x = [b["cx"] for b in entity_boxes]
centers_y = [b["cy"] for b in entity_boxes]

# DBSCAN-like 간단한 클러스터링
def cluster_points_2d(boxes, gap=20):
    """2D 클러스터링: 인접 엔티티 그룹화"""
    assigned = [False] * len(boxes)
    clusters = []

    for i in range(len(boxes)):
        if assigned[i]:
            continue
        cluster = [i]
        assigned[i] = True
        queue = [i]
        while queue:
            curr = queue.pop(0)
            b1 = boxes[curr]
            for j in range(len(boxes)):
                if assigned[j]:
                    continue
                b2 = boxes[j]
                # 바운딩 박스간 거리 (gap보다 작으면 같은 클러스터)
                dx = max(0, max(b1["xmin"], b2["xmin"]) - min(b1["xmax"], b2["xmax"]))
                dy = max(0, max(b1["ymin"], b2["ymin"]) - min(b1["ymax"], b2["ymax"]))
                if dx < gap and dy < gap:
                    cluster.append(j)
                    assigned[j] = True
                    queue.append(j)
        clusters.append(cluster)

    return clusters

print("\n=== 클러스터링 시도 (gap=20) ===")
clusters = cluster_points_2d(entity_boxes, gap=20)
print(f"클러스터 수: {len(clusters)}")

for i, cl in enumerate(clusters):
    xmins = [entity_boxes[j]["xmin"] for j in cl]
    xmaxs = [entity_boxes[j]["xmax"] for j in cl]
    ymins = [entity_boxes[j]["ymin"] for j in cl]
    ymaxs = [entity_boxes[j]["ymax"] for j in cl]
    print(f"\n  Cluster {i+1}: {len(cl)} entities")
    print(f"    X: {min(xmins):.2f} ~ {max(xmaxs):.2f}  (width: {max(xmaxs)-min(xmins):.2f})")
    print(f"    Y: {min(ymins):.2f} ~ {max(ymaxs):.2f}  (height: {max(ymaxs)-min(ymins):.2f})")
