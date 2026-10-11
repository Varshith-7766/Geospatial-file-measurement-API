# Geospatial File Measurement API

FastAPI service: upload a Shapefile (`.zip`) or `.kml`, get per-feature measurements with correct CRS handling.

## Setup

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
# docs: http://localhost:8000/docs
```

Run tests: `python -m pytest tests/ -q`

## API

### Upload — `POST /api/files/`
```bash
curl -F "file=@sample.kml" http://localhost:8000/api/files/
curl -F "file=@sample_files.zip" http://localhost:8000/api/files/
```
Response `201`:
```json
{"id": "c31cdf8600ca", "filename": "sample.kml", "feature_count": 3, "crs": "EPSG:4326", "status": "COMPLETED"}
```

### File info — `GET /api/files/{id}/`
```bash
curl http://localhost:8000/api/files/c31cdf8600ca/
```
```json
{"id": "c31cdf8600ca", "filename": "sample.kml", "feature_count": 3, "crs": "EPSG:4326", "status": "COMPLETED"}
```

### Measurements — `GET /api/files/{id}/measurements/`
```bash
curl http://localhost:8000/api/files/c31cdf8600ca/measurements/
```
```json
{
  "id": "c31cdf8600ca", "crs": "EPSG:4326", "count": 3,
  "measurements": [
    {"feature_id": 0, "geometry_type": "Polygon", "measurement_type": "area", "value": 1200592.7, "unit": "sq_meters"},
    {"feature_id": 1, "geometry_type": "LineString", "measurement_type": "length", "value": 1552.3, "unit": "meters"},
    {"feature_id": 2, "geometry_type": "Point", "measurement_type": "none", "value": null, "unit": null}
  ],
  "features": [
    {"id": 0, "geometry_type": "Polygon", "geometry": {...}, "crs": "EPSG:4326", "properties": {"name": "..."}}
  ]
}
```

Errors: `400` bad file type/corrupt, `404` unknown id. Unsupported geometry → `measurement_type: "unsupported"`, never a crash.

## Architecture

```
app/main.py  — 3 endpoints + in-memory store (dict id → {filename, crs, feats})
app/geo.py   — parse_geospatial / to_measurements / to_feature_list
tests/test_api.py — KML upload→info→measurements + rejection test
```

**File-processing flow:** validate extension → size check (50MB) → parse.
Shapefile: `zipfile` (stdlib) → `pyshp` reads `.shp/.shx/.dbf` from memory → `.prj` WKT → CRS via `pyproj` (default `EPSG:4326` if missing).
KML: stdlib `xml.etree` extracts Point/LineString/Polygon coords per Placemark (spec = always `EPSG:4326`).

**Measurement flow:** `Polygon/MultiPolygon → area`, `LineString/MultiLineString → length`, `Point → none`, else `unsupported`. Geometries projected to metres first, then `shapely.area/length`.

**CRS handling:** if `CRS.is_geographic`, reproject with `pyproj.Transformer` to the UTM zone of the dataset centroid (`326xx` N / `327xx` S, fallback `EPSG:3857`). Projected inputs are measured as-is. Never measures in degrees.

## Design decisions

- **FastAPI over Django** — 3 endpoints, no auth/admin/ORM needed; FastAPI = 1 file + auto `/docs`.
- **No GDAL (`fiona`/`geopandas`/`pyogrio`)** — no Windows wheels for Python 3.14, needs native GDAL build. `pyshp + shapely + pyproj` are pure-Python/wheeled and cover everything the spec asks. Trade-off: no exotic drivers (GeoJSON/GPKG would need GDAL — add `pyogrio` later).
- **In-memory store, not a DB** — spec has no persistence requirement; add SQLite/PostGIS when restart-survival matters.
- **Manual KML parser (stdlib)** — KML is simple XML; avoids the `LIBKML` driver dependency entirely.
- **Per-dataset UTM** over fixed Web-Mercator — UTM preserves local distances/areas; Mercator distorts area badly off-equator.

## Learnings & future scope

- Learned: shapefiles are multi-file archives (`.shp/.shx/.dbf/.prj` all matter); KML is always lon/lat; degree math is meaningless — project first; pyshp ring winding affects GeoJSON conversion.
- Next: persistent storage (PostGIS), async/background jobs for large files, pagination on measurements, GeoJSON/GPKG support via pyogrio, Dockerfile + CI, auth/rate-limits.
