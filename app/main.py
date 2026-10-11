from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
import uuid

from .geo import parse_geospatial, to_feature_list, to_measurements

app = FastAPI(title="Geospatial File Measurement API", version="1.0.0")

# ponytail: in-memory store, add DB (sqlite/postgis) when persistence across restarts matters
STORE: dict = {}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/files/", status_code=201)
async def upload_file(file: UploadFile = File(...)):
    name = (file.filename or "").lower()
    if not (name.endswith(".zip") or name.endswith(".kml")):
        raise HTTPException(400, "Only .zip (shapefile) or .kml accepted")
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Empty file")
    if len(raw) > 50 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 50MB)")
    try:
        feats, crs_str = parse_geospatial(raw, file.filename or "upload")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception:
        raise HTTPException(400, "Could not parse geospatial file (invalid zip/shp/kml?)")
    fid = uuid.uuid4().hex[:12]
    STORE[fid] = {"filename": file.filename, "crs": crs_str, "feats": feats}
    return {"id": fid, "filename": file.filename,
            "feature_count": len(feats), "crs": crs_str, "status": "COMPLETED"}


@app.get("/api/files/{fid}/")
def file_info(fid: str):
    rec = STORE.get(fid)
    if not rec:
        raise HTTPException(404, "File not found")
    return {"id": fid, "filename": rec["filename"],
            "feature_count": len(rec["feats"]), "crs": rec["crs"], "status": "COMPLETED"}


@app.get("/api/files/{fid}/measurements/")
def measurements(fid: str):
    rec = STORE.get(fid)
    if not rec:
        raise HTTPException(404, "File not found")
    feats, crs = rec["feats"], rec["crs"]
    return {"id": fid, "crs": crs, "count": len(feats),
            "measurements": to_measurements(feats, crs),
            "features": to_feature_list(feats, crs)}
