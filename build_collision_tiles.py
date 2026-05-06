import json
import math
from collections import defaultdict
from pathlib import Path

import mapbox_vector_tile

INPUT_GEOJSON = Path("Traffic Collisions - 4326.geojson")
OUTPUT_ROOT = Path("tiles/collisions")
LAYER_NAME = "collisions"
MIN_ZOOM = 9
MAX_ZOOM = 13
EXTENT = 4096


def lonlat_to_tile(lon: float, lat: float, z: int) -> tuple[int, int]:
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    x = min(max(x, 0), n - 1)
    y = min(max(y, 0), n - 1)
    return x, y


def tile_bounds_lonlat(x: int, y: int, z: int) -> tuple[float, float, float, float]:
    n = 2 ** z
    west = x / n * 360.0 - 180.0
    east = (x + 1) / n * 360.0 - 180.0
    north = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n))))
    south = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * (y + 1) / n))))
    return west, south, east, north


def extract_point(feature: dict) -> tuple[float, float] | None:
    geom = feature.get("geometry") or {}
    gtype = geom.get("type")
    coords = geom.get("coordinates")

    if gtype == "Point" and isinstance(coords, list) and len(coords) >= 2:
        lon, lat = coords[0], coords[1]
    elif gtype == "MultiPoint" and isinstance(coords, list) and coords and len(coords[0]) >= 2:
        lon, lat = coords[0][0], coords[0][1]
    else:
        return None

    try:
        lon = float(lon)
        lat = float(lat)
    except (TypeError, ValueError):
        return None

    if lon == 0.0 and lat == 0.0:
        return None
    if not (-180.0 <= lon <= 180.0 and -85.05113 <= lat <= 85.05113):
        return None

    return lon, lat


def slim_properties(props: dict) -> dict:
    out = {
        "id": props.get("_id"),
        "year": props.get("OCC_YEAR"),
        "injury": props.get("INJURY_COLLISIONS"),
        "fatal": props.get("FATALITIES"),
        "division": props.get("DIVISION"),
    }
    return {k: v for k, v in out.items() if v is not None}


def main() -> None:
    if not INPUT_GEOJSON.exists():
        raise FileNotFoundError(f"Missing input file: {INPUT_GEOJSON}")

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    with INPUT_GEOJSON.open("r", encoding="utf-8") as f:
        data = json.load(f)

    raw_features = data.get("features", [])

    points: list[tuple[float, float, dict]] = []
    skipped = 0
    for feat in raw_features:
        point = extract_point(feat)
        if point is None:
            skipped += 1
            continue

        lon, lat = point
        props = slim_properties((feat.get("properties") or {}))
        points.append((lon, lat, props))

    print(f"Loaded {len(raw_features):,} features")
    print(f"Valid points for tiles: {len(points):,}")
    print(f"Skipped invalid/missing points: {skipped:,}")

    total_tiles = 0
    total_features_written = 0

    for z in range(MIN_ZOOM, MAX_ZOOM + 1):
        buckets: dict[tuple[int, int], list[dict]] = defaultdict(list)

        for lon, lat, props in points:
            x, y = lonlat_to_tile(lon, lat, z)
            buckets[(x, y)].append(
                {
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "properties": props,
                }
            )

        tiles_this_zoom = 0
        feats_this_zoom = 0

        for (x, y), feats in buckets.items():
            bounds = tile_bounds_lonlat(x, y, z)
            tile = mapbox_vector_tile.encode(
                {"name": LAYER_NAME, "features": feats},
                default_options={
                    "quantize_bounds": bounds,
                    "y_coord_down": True,
                    "extents": EXTENT,
                },
            )

            out_dir = OUTPUT_ROOT / str(z) / str(x)
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"{y}.pbf"
            out_path.write_bytes(tile)

            tiles_this_zoom += 1
            feats_this_zoom += len(feats)

        total_tiles += tiles_this_zoom
        total_features_written += feats_this_zoom

        print(
            f"z{z}: {tiles_this_zoom:,} tiles, {feats_this_zoom:,} encoded points"
        )

    print("Done")
    print(f"Total tiles: {total_tiles:,}")
    print(f"Total encoded points (across zoom levels): {total_features_written:,}")


if __name__ == "__main__":
    main()
