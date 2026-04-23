from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple
import json
from uuid import uuid4
import numpy as np


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp_" + uuid4().hex)
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _write_json(path: Path, payload: Any) -> None:
    _write_text_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2))


def _cell_polygon(lon_grid, lat_grid, i: int, j: int):
    return [
        [float(lon_grid[i, j]), float(lat_grid[i, j])],
        [float(lon_grid[i, j + 1]), float(lat_grid[i, j + 1])],
        [float(lon_grid[i + 1, j + 1]), float(lat_grid[i + 1, j + 1])],
        [float(lon_grid[i + 1, j]), float(lat_grid[i + 1, j])],
        [float(lon_grid[i, j]), float(lat_grid[i, j])],
    ]


def _rgba(r: int, g: int, b: int, a: float) -> str:
    return f"rgba({int(np.clip(r, 0, 255))},{int(np.clip(g, 0, 255))},{int(np.clip(b, 0, 255))},{a})"


def _aspect_color(value: float) -> Tuple[str, str]:
    if value <= 0.0:
        r, g, b = 176, 176, 176
    elif value < 22.5:
        r, g, b = 255, 0, 0
    elif value < 67.5:
        r, g, b = 255, 166, 0
    elif value < 112.5:
        r, g, b = 255, 255, 0
    elif value < 157.5:
        r, g, b = 0, 255, 0
    elif value < 202.5:
        r, g, b = 0, 255, 255
    elif value < 247.5:
        r, g, b = 0, 166, 255
    elif value < 292.5:
        r, g, b = 0, 0, 255
    elif value < 337.5:
        r, g, b = 255, 0, 255
    else:
        r, g, b = 255, 0, 0
    return _rgba(r, g, b, 0.7), _rgba(r // 2, g // 2, b // 2, 1.0)


def _slope_color(value: float) -> Tuple[str, str]:
    # Keep exactly the same bins/palette as frontend calculateSlopeColor.
    if value <= 7.4:
        r, g, b = 56, 168, 0
    elif value < 16.568:
        r, g, b = 94, 189, 0
    elif value < 23.971:
        r, g, b = 139, 209, 0
    elif value < 29.96:
        r, g, b = 193, 232, 0
    elif value < 35.25:
        r, g, b = 255, 255, 0
    elif value < 41.244:
        r, g, b = 255, 191, 0
    elif value < 49.0:
        r, g, b = 255, 128, 0
    elif value < 70.5:
        r, g, b = 255, 64, 0
    elif value < 89.0:
        r, g, b = 255, 0, 0
    else:
        r, g, b = 255, 0, 0
    return _rgba(r, g, b, 0.7), _rgba(r // 2, g // 2, b // 2, 1.0)


def _continuous_color(value: float, value_min: float, value_max: float) -> Tuple[str, str]:
    value_range = value_max - value_min if value_max > value_min else 1.0
    norm_val = (value - value_min) / value_range if value_range > 0 else 0.5
    norm_val = float(np.clip(norm_val, 0.0, 1.0))
    if norm_val < 0.5:
        r = 255
        g = int(norm_val * 2.0 * 255.0)
        b = 0
    else:
        r = int((1.0 - norm_val) * 2.0 * 255.0)
        g = 255
        b = 0
    return _rgba(r, g, b, 0.7), _rgba(r // 2, g // 2, b // 2, 1.0)


def _fill_nonfinite(grid: np.ndarray) -> np.ndarray:
    out = grid.astype(np.float64).copy()
    finite_mask = np.isfinite(out)
    if not np.any(finite_mask):
        return np.zeros_like(out)

    fallback = float(np.nanmean(out[finite_mask]))

    rows, cols = out.shape
    for _ in range(2):
        bad = ~np.isfinite(out)
        if not np.any(bad):
            break
        for i in range(rows):
            for j in range(cols):
                if not np.isfinite(out[i, j]):
                    vals = []
                    for di in (-1, 0, 1):
                        for dj in (-1, 0, 1):
                            if di == 0 and dj == 0:
                                continue
                            ni, nj = i + di, j + dj
                            if 0 <= ni < rows and 0 <= nj < cols and np.isfinite(out[ni, nj]):
                                vals.append(float(out[ni, nj]))
                    out[i, j] = float(np.mean(vals)) if vals else fallback

    out[~np.isfinite(out)] = fallback
    return out


def _smooth_aspect_deg(aspect_grid: np.ndarray) -> np.ndarray:
    rows, cols = aspect_grid.shape
    rad = np.deg2rad(np.mod(aspect_grid, 360.0))
    sinv = np.sin(rad)
    cosv = np.cos(rad)
    out = np.empty_like(aspect_grid)
    for i in range(rows):
        for j in range(cols):
            i0 = max(0, i - 1)
            i1 = min(rows, i + 2)
            j0 = max(0, j - 1)
            j1 = min(cols, j + 2)
            s = float(np.mean(sinv[i0:i1, j0:j1]))
            c = float(np.mean(cosv[i0:i1, j0:j1]))
            ang = np.degrees(np.arctan2(s, c))
            if ang < 0.0:
                ang += 360.0
            out[i, j] = ang
    return out


def export_grid_as_geojson(path: Path, lon_grid, lat_grid, value_grid, value_name: str, stride: int = 1) -> int:
    features: List[Dict] = []
    n_rows, n_cols = value_grid.shape

    # Fill non-finite values only; do not smooth aspect for parity with frontend.
    value_grid_filled = _fill_nonfinite(value_grid)

    value_min = float(np.min(value_grid_filled))
    value_max = float(np.max(value_grid_filled))

    for i in range(0, n_rows - 1, stride):
        for j in range(0, n_cols - 1, stride):
            value = float(value_grid_filled[i, j])
            if value_name == "aspect_deg":
                fill_color_rgba, stroke_color_rgba = _aspect_color(value)
            elif value_name == "slope_deg":
                fill_color_rgba, stroke_color_rgba = _slope_color(value)
            else:
                fill_color_rgba, stroke_color_rgba = _continuous_color(value, value_min, value_max)

            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "value": value,
                        value_name: value,
                        "fill": fill_color_rgba,
                        "stroke": stroke_color_rgba,
                    },
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [_cell_polygon(lon_grid, lat_grid, i, j)],
                    },
                }
            )

    payload = {"type": "FeatureCollection", "features": features}
    _write_json(path, payload)
    return len(features)


def export_path_as_geojson(path: Path, path_lonlat: Iterable[Tuple[float, float]]) -> int:
    coords = [[float(lon), float(lat)] for lon, lat in path_lonlat]
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "optimal_path"},
                "geometry": {"type": "LineString", "coordinates": coords},
            }
        ],
    }
    _write_json(path, payload)
    return 1


def export_path_as_czml(path: Path, path_lonlat: Iterable[Tuple[float, float]]) -> int:
    coords = list(path_lonlat)
    cartographic_deg: List[float] = []
    for lon, lat in coords:
        cartographic_deg.extend([0.0, float(lon), float(lat), 5.0])

    payload = [
        {"id": "document", "name": "path", "version": "1.0"},
        {
            "id": "path_line",
            "name": "DEM Path",
            "polyline": {
                "positions": {"cartographicDegrees": cartographic_deg},
                "material": {"solidColor": {"color": {"rgba": [255, 60, 60, 220]}}},
                "width": 4,
            },
        },
    ]
    _write_json(path, payload)
    return 1


def export_grid_as_czml(path: Path, lon_grid, lat_grid, value_grid, value_name: str, stride: int = 6) -> int:
    entities: List[Dict] = [{"id": "document", "name": value_name, "version": "1.0"}]
    n_rows, n_cols = value_grid.shape
    idx = 0
    for i in range(0, n_rows, stride):
        for j in range(0, n_cols, stride):
            value = float(value_grid[i, j])
            entities.append(
                {
                    "id": f"{value_name}_{idx}",
                    "name": f"{value_name}:{value:.4f}",
                    "position": {
                        "cartographicDegrees": [
                            float(lon_grid[i, j]),
                            float(lat_grid[i, j]),
                            20.0,
                        ]
                    },
                    "point": {
                        "pixelSize": 5,
                        "color": {"rgba": [40, 220, 255, 220]},
                        "outlineColor": {"rgba": [8, 32, 56, 255]},
                        "outlineWidth": 1,
                    },
                    "properties": {value_name: value},
                }
            )
            idx += 1

    _write_json(path, entities)
    return idx


def export_path_as_kml(path: Path, path_lonlat: Iterable[Tuple[float, float]]) -> int:
    coords = " ".join([f"{lon},{lat},10" for lon, lat in path_lonlat])
    xml = f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<kml xmlns=\"http://www.opengis.net/kml/2.2\">
  <Document>
    <Placemark>
      <name>DEM Path</name>
      <Style>
        <LineStyle><color>ff2c2cff</color><width>3</width></LineStyle>
      </Style>
      <LineString>
        <tessellate>1</tessellate>
        <coordinates>{coords}</coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>
"""
    _write_text_atomic(path, xml)
    return 1


def export_grid_as_kml(path: Path, lon_grid, lat_grid, value_grid, value_name: str, stride: int = 6) -> int:
    placemarks: List[str] = []
    n_rows, n_cols = value_grid.shape
    for i in range(0, n_rows - 1, stride):
        for j in range(0, n_cols - 1, stride):
            ring = _cell_polygon(lon_grid, lat_grid, i, j)
            coords = " ".join([f"{lon},{lat},0" for lon, lat in ring])
            value = float(value_grid[i, j])
            placemarks.append(
                f"""
    <Placemark>
      <name>{value_name}:{value:.4f}</name>
      <Polygon>
        <outerBoundaryIs><LinearRing><coordinates>{coords}</coordinates></LinearRing></outerBoundaryIs>
      </Polygon>
    </Placemark>"""
            )

    xml = f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<kml xmlns=\"http://www.opengis.net/kml/2.2\">
  <Document>
{''.join(placemarks)}
  </Document>
</kml>
"""
    _write_text_atomic(path, xml)
    return len(placemarks)
