# sample_elev_local.py
import argparse
import math
import pandas as pd
import numpy as np
import rasterio
from tqdm import tqdm

def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    phi1 = math.radians(lat1); phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1); dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2*R*math.asin(math.sqrt(a))

def compute_cumulative_distance(lat_arr, lon_arr):
    n = len(lat_arr)
    d = np.zeros(n, dtype=float)
    for i in range(1, n):
        d[i] = d[i-1] + haversine_m(lat_arr[i-1], lon_arr[i-1], lat_arr[i], lon_arr[i])
    return d

def sample_elevations(dem_path, lat_lon_list, batch_size=20000):
    """Возвращает список высот (meters) в том же порядке, что lat_lon_list."""
    n = len(lat_lon_list)
    elevs = [None]*n
    # rasterio.sample принимает (lon, lat)
    coords = [(float(lon), float(lat)) for lat, lon in lat_lon_list]
    with rasterio.open(dem_path) as ds:
        nodata = ds.nodatavals[0]
        idx = 0
        for i in range(0, n, batch_size):
            chunk = coords[i:i+batch_size]
            for val in ds.sample(chunk):
                v = None
                try:
                    v = float(val[0])
                    if nodata is not None and v == nodata:
                        v = None
                except Exception:
                    v = None
                elevs[idx] = v
                idx += 1
    return elevs

def compute_gradients(elevations, distances):
    n = len(elevations)
    grads = [None]*n
    grads[0] = 0.0
    for i in range(1, n):
        e0 = elevations[i-1]; e1 = elevations[i]
        if e0 is None or e1 is None:
            grads[i] = None
            continue
        dx = distances[i] - distances[i-1]
        if dx == 0:
            grads[i] = 0.0
        else:
            grads[i] = (e1 - e0) / dx * 100.0
    return grads

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", "-i", required=True, help="CSV input with columns lat,lon  (any order of columns ok)")
    p.add_argument("--dem", "-d", required=True, help="Path to local DEM (GeoTIFF or VRT)")
    p.add_argument("--output", "-o", default="route_with_elev_local.csv", help="Output CSV path")
    p.add_argument("--batch", type=int, default=20000, help="Batch size for rasterio.sample")
    args = p.parse_args()

    df = pd.read_csv(args.input)
    if not {'lat','lon'}.issubset(df.columns):
        raise SystemExit("Входной CSV должен содержать столбцы 'lat' и 'lon'.")

    lat_arr = df['lat'].astype(float).to_numpy()
    lon_arr = df['lon'].astype(float).to_numpy()

    # вычисляем кумулятивную дистанцию, если нет
    if 'dist_m' in df.columns:
        dists = df['dist_m'].astype(float).to_numpy()
    else:
        print("dist_m не найден — вычисляю по Haversine.")
        dists = compute_cumulative_distance(lat_arr, lon_arr)

    points = list(zip(lat_arr, lon_arr))
    print(f"Всего точек: {len(points)}. Сэмплирую высоты из DEM: {args.dem}")
    elevations = sample_elevations(args.dem, points, batch_size=args.batch)

    print("Вычисляю градиенты...")
    gradients = compute_gradients(elevations, dists)

    df['elevation_m'] = elevations
    df['gradient_pct'] = gradients
    df.to_csv(args.output, index=False)
    print("Сохранено в", args.output)

if __name__ == "__main__":
    main()
