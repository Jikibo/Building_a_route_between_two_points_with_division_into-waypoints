# build_route_100k_and_sample.py
# Надёжный вариант, игнорирующий системные прокси (requests.session.trust_env=False)
import argparse, requests, math, numpy as np, pandas as pd, time, sys
from tqdm import tqdm
import rasterio
import polyline

def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    phi1 = math.radians(lat1); phi2 = math.radians(lat2)
    dphi = math.radians(lat2-lat1); dlambda = math.radians(lon2-lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2*R*math.asin(math.sqrt(a))

# создаём сессию единожды и запрещаем использование env-прокси
SESSION = requests.Session()
SESSION.trust_env = False  # КЛЮЧЕВОЕ: игнорируем HTTP(S)_PROXY из окружения

def request_osrm_polyline(url, timeout=120):
    # используем SESSION.get, чтобы игнорировать прокси
    r = SESSION.get(url, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:400]}")
    js = r.json()
    if js.get("code") != "Ok":
        raise RuntimeError(f"OSRM code != Ok: {js.get('code')}")
    enc = js['routes'][0]['geometry']
    coords = polyline.decode(enc)  # list of (lat, lon)
    return coords

def get_route_single(osrm_url_template, start, end, timeout=120):
    url = osrm_url_template.format(lon1=start[1], lat1=start[0], lon2=end[1], lat2=end[0])
    params = {"overview":"full", "geometries":"polyline"}
    full_url = requests.Request('GET', url, params=params).prepare().url
    print("Single request URL:", full_url)
    return request_osrm_polyline(full_url, timeout=timeout)

def interpolate_linear(a, b, t):
    return (a[0] + (b[0]-a[0])*t, a[1] + (b[1]-a[1])*t)

def get_route_segmented(osrm_url_template, start, end, segments=5, timeout=120):
    pts = [interpolate_linear(start, end, i/segments) for i in range(0, segments+1)]
    all_coords = []
    for i in range(segments):
        s = pts[i]; e = pts[i+1]
        url = osrm_url_template.format(lon1=s[1], lat1=s[0], lon2=e[1], lat2=e[0])
        params = {"overview":"full", "geometries":"polyline"}
        full_url = requests.Request('GET', url, params=params).prepare().url
        print(f"Segment {i+1}/{segments}: {full_url}")
        coords = request_osrm_polyline(full_url, timeout=timeout)
        if all_coords:
            if coords and coords[0] == all_coords[-1]:
                all_coords.extend(coords[1:])
            else:
                all_coords.extend(coords)
        else:
            all_coords.extend(coords)
        time.sleep(0.2)
    return all_coords

def get_route_with_fallback(osrm_url_template, start, end):
    try:
        coords = get_route_single(osrm_url_template, start, end, timeout=120)
        print("Single request succeeded. Vertices:", len(coords))
        return coords
    except Exception as e:
        print("Single request failed:", str(e))
    for seg in (4, 8, 16):
        try:
            print(f"Trying segmented request with {seg} pieces...")
            coords = get_route_segmented(osrm_url_template, start, end, segments=seg, timeout=90)
            print("Segmented request succeeded. Vertices total:", len(coords))
            return coords
        except Exception as e:
            print(f"Segmented {seg} failed:", str(e))
    raise SystemExit("Не удалось получить маршрут ни единым запросом, ни сегментированием.")

def densify_along_path(coords, n_points):
    seg_lengths = []
    for i in range(len(coords)-1):
        seg_lengths.append(haversine_m(coords[i][0], coords[i][1], coords[i+1][0], coords[i+1][1]))
    seg_lengths = np.array(seg_lengths)
    cum = np.concatenate(([0.0], np.cumsum(seg_lengths)))
    total = cum[-1]
    targets = np.linspace(0, total, n_points)
    out = np.empty((n_points,2), dtype=float)
    seg_i = 0
    for ti,d in enumerate(targets):
        while seg_i < len(seg_lengths)-1 and d > cum[seg_i+1]:
            seg_i += 1
        d0 = cum[seg_i]; seg_len = seg_lengths[seg_i]
        frac = 0.0 if seg_len==0 else max(0.0, min(1.0, (d-d0)/seg_len))
        lat0, lon0 = coords[seg_i]; lat1, lon1 = coords[seg_i+1]
        out[ti,0] = lat0 + (lat1-lat0)*frac
        out[ti,1] = lon0 + (lon1-lon0)*frac
    return out, total

def sample_elevations_rasterio(dem_path, latlon_array, batch=50000):
    n = latlon_array.shape[0]
    elevs = [None]*n
    coords = [(float(lon), float(lat)) for lat, lon in latlon_array]
    with rasterio.open(dem_path) as ds:
        nodata = ds.nodatavals[0]
        idx=0
        for i in range(0, n, batch):
            chunk = coords[i:i+batch]
            for v in ds.sample(chunk):
                val = None
                try:
                    val = float(v[0])
                    if nodata is not None and val == nodata:
                        val = None
                except Exception:
                    val = None
                elevs[idx] = val
                idx+=1
    return elevs

def compute_gradients(elev, dists):
    n=len(elev); grads=[None]*n; grads[0]=0.0
    for i in range(1,n):
        e0=elev[i-1]; e1=elev[i]
        if e0 is None or e1 is None:
            grads[i]=None; continue
        dx=dists[i]-dists[i-1]
        grads[i]=0.0 if dx==0 else (e1-e0)/dx*100.0
    return grads

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--start_lat", required=True, type=float)
    p.add_argument("--start_lon", required=True, type=float)
    p.add_argument("--end_lat", required=True, type=float)
    p.add_argument("--end_lon", required=True, type=float)
    p.add_argument("--osrm_url", required=True)
    p.add_argument("--dem", required=True)
    p.add_argument("--out", default="route_piter_moskva_100k.csv")
    p.add_argument("--n", type=int, default=100000)
    p.add_argument("--batch", type=int, default=50000)
    args=p.parse_args()

    start=(args.start_lat, args.start_lon); end=(args.end_lat, args.end_lon)
    print("Requesting route (with fallback segmentation if needed)...")
    coords = get_route_with_fallback(args.osrm_url, start, end)
    if len(coords) < 2:
        raise SystemExit("Получено <2 вершин, не могу интерполировать.")
    print("Vertices returned:", len(coords))
    print("Densifying to", args.n, "points...")
    pts, total_len = densify_along_path(coords, args.n)
    print("Total length (m):", total_len)
    dists = np.zeros(args.n, dtype=float)
    for i in range(1, args.n):
        dists[i] = dists[i-1] + haversine_m(pts[i-1,0], pts[i-1,1], pts[i,0], pts[i,1])
    print("Sampling elevations from DEM...")
    elevs = sample_elevations_rasterio(args.dem, pts, batch=args.batch)
    print("Computing gradients...")
    grads = compute_gradients(elevs, dists)
    df = pd.DataFrame({
        "idx": np.arange(args.n),
        "lat": pts[:,0],
        "lon": pts[:,1],
        "dist_m": dists,
        "elevation_m": elevs,
        "gradient_pct": grads
    })
    df.to_csv(args.out, index=False)
    print("Saved:", args.out)

if __name__=="__main__":
    main()
