"""Parse + measure without GDAL: pyshp for shapefiles, stdlib for KML."""
import io, zipfile
from shapely.geometry import shape
from shapely import transform as shp_transform_xy
from pyproj import CRS, Transformer


def parse_geospatial(raw: bytes, filename: str):
    return _read_kml(raw) if filename.lower().endswith(".kml") else _read_shp_zip(raw)


def _read_shp_zip(raw: bytes):
    import shapefile
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise ValueError("Invalid zip file")
    blobs = {n.split("/")[-1].lower(): zf.read(n) for n in zf.namelist() if not n.endswith("/")}
    shp = next((v for k, v in blobs.items() if k.endswith(".shp")), None)
    if not shp:
        raise ValueError("Zip must contain a .shp (+ .shx/.dbf)")
    kw = {"shp": io.BytesIO(shp)}
    for ext in ("shx", "dbf"):
        b = next((v for k, v in blobs.items() if k.endswith(f".{ext}")), None)
        if b:
            kw[ext] = io.BytesIO(b)
    try:
        rdr = shapefile.Reader(**kw)
    except Exception:
        raise ValueError("Could not read shapefile (corrupt or missing .shx/.dbf?)")
    names = [f[0] for f in rdr.fields[1:]]
    feats = [{"geometry": shape(s.__geo_interface__), "properties": dict(zip(names, rec))}
             for s, rec in zip(rdr.shapes(), rdr.records()) if s.__geo_interface__]
    if not feats:
        raise ValueError("Shapefile contains no features")
    prj = next((v.decode("utf-8", "ignore") for k, v in blobs.items() if k.endswith(".prj")), None)
    crs = "EPSG:4326"
    if prj:
        try:
            c = CRS.from_wkt(prj)
            crs = f"EPSG:{c.to_epsg()}" if c.to_epsg() else c.to_string()
        except Exception:
            pass
    return feats, crs


def _coords(text):
    pts = []
    for tok in (text or "").strip().split():
        p = tok.split(",")
        if len(p) >= 2:
            pts.append((float(p[0]), float(p[1])))
    return pts


def _read_kml(raw: bytes):
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        raise ValueError("Invalid KML")
    tag = lambda el: el.tag.split("}")[-1]  # ns-agnostic
    feats = []
    for pm in root.iter():
        if tag(pm) != "Placemark":
            continue
        props = {tag(c): (c.text or "").strip() for c in pm
                 if tag(c) in ("name", "description") and c.text}
        for el in pm.iter():
            t, txt = tag(el), "".join(el.itertext())
            if t == "Point":
                c = _coords(next((x for x in el.iter() if tag(x) == "coordinates"), None).text
                            if any(tag(x) == "coordinates" for x in el.iter()) else "")
                if c:
                    feats.append({"geometry": shape({"type": "Point", "coordinates": c[0]}), "properties": props})
            elif t in ("LineString", "Polygon"):
                found = [x for x in el.iter() if tag(x) == "coordinates"]
                for co in found[:1]:
                    c = _coords(co.text)
                    if len(c) >= 2:
                        g = {"type": "LineString", "coordinates": c} if t == "LineString" \
                            else {"type": "Polygon", "coordinates": [c]}
                        feats.append({"geometry": shape(g), "properties": props})
                break
    if not feats:
        raise ValueError("No parseable Placemarks found in KML")
    return feats, "EPSG:4326"  # KML spec is always lon/lat


def _utm_epsg(feats, src: str) -> str:
    try:
        sc, g = CRS.from_user_input(src), [f["geometry"] for f in feats if f["geometry"] and not f["geometry"].is_empty]
        b = shape({"type": "GeometryCollection", "geometries": [x.__geo_interface__ for x in g]}).bounds
        lon, lat = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        if sc.is_geographic:  # deg -> utm zone math
            z = int((lon + 180) // 6) + 1
            return f"EPSG:{32600 + z if lat >= 0 else 32700 + z}"
        return src
    except Exception:
        return "EPSG:3857"


def _project(g, src: str, dst: str):
    if src == dst:
        return g
    return shp_transform_xy(g, Transformer.from_crs(src, dst, always_xy=True).transform, interleaved=False)


def measure_one(g, pg):
    t = (g.geom_type or "").lower()
    if "polygon" in t:
        return ("area", float(pg.area), "sq_meters")
    if "line" in t:
        return ("length", float(pg.length), "meters")
    if "point" in t:
        return ("none", None, None)
    return ("unsupported", None, None)  # graceful: never crash on exotic types


def to_measurements(feats, src_crs: str):
    dst = _utm_epsg(feats, src_crs)
    out = []
    for i, f in enumerate(feats):
        g = f["geometry"]
        try:
            m = measure_one(g, _project(g, src_crs, dst)) if g and not g.is_empty else ("empty", None, None)
        except Exception:
            m = ("error", None, None)
        out.append({"feature_id": i, "geometry_type": g.geom_type if g else None,
                    "measurement_type": m[0], "value": m[1], "unit": m[2]})
    return out


def to_feature_list(feats, crs: str):
    return [{"id": i, "geometry_type": f["geometry"].geom_type if f["geometry"] else None,
             "geometry": f["geometry"].__geo_interface__ if f["geometry"] else None,
             "crs": crs, "properties": f["properties"]} for i, f in enumerate(feats)]


if __name__ == "__main__":  # ponytail self-check: 1deg square at equator ~12.3e9 m²
    from shapely.geometry import Polygon
    f = [{"geometry": Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]), "properties": {}}]
    m = to_measurements(f, "EPSG:4326")[0]
    assert m["measurement_type"] == "area" and 1.2e10 < m["value"] < 1.3e10, m
    print("demo ok:", m)
