from fastapi.testclient import TestClient
from app.main import app

KML = b"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<Placemark><name>sq</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
0,0,0 0.01,0,0 0.01,0.01,0 0,0.01,0 0,0,0</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
<Placemark><name>ln</name><LineString><coordinates>0,0,0 0.01,0,0</coordinates></LineString></Placemark>
<Placemark><name>pt</name><Point><coordinates>0,0,0</coordinates></Point></Placemark>
</Document></kml>"""

c = TestClient(app)

def test_flow():
    r = c.post("/api/files/", files={"file": ("survey.kml", KML, "application/vnd.google-earth.kml+xml")})
    assert r.status_code == 201, r.text
    fid = r.json()["id"]
    assert r.json()["feature_count"] == 3
    info = c.get(f"/api/files/{fid}/").json()
    assert info["crs"] == "EPSG:4326" and info["status"] == "COMPLETED"
    m = c.get(f"/api/files/{fid}/measurements/").json()
    types = {x["measurement_type"] for x in m["measurements"]}
    assert {"area", "length", "none"} <= types, m
    area = next(x["value"] for x in m["measurements"] if x["measurement_type"] == "area")
    length = next(x["value"] for x in m["measurements"] if x["measurement_type"] == "length")
    assert 1_000_000 < area < 1_500_000 and 900 < length < 1300, (area, length)
    assert c.get("/api/files/nope/").status_code == 404

def test_reject():
    r = c.post("/api/files/", files={"file": ("x.txt", b"hi", "text/plain")})
    assert r.status_code == 400
