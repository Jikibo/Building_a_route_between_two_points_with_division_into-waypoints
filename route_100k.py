"""
route_100k.py
1) Берёт маршрут по дорогам от Санкт-Петербурга до Москвы (OSRM demo server).
2) Интерполирует путь на N = 100000 равномерных по длине точек.
3) (Опционально) Запрашивает высоты для точек (Open-Elevation / Open-Meteo).
4) Вычисляет градиент (уклон) между соседними точками.
5) Сохраняет CSV: idx, lat, lon, dist_m, elevation_m, gradient_pct

ВАЖНО:
 - Public OSRM / Open-Elevation сервисы имеют ограничения и не гарантируют обслуживание
   больших пакетов запросов. Для 100k точек рекомендуется либо:
     * использовать OSRM / elevation локально (развернуть свои серверы), либо
     * запрашивать высоты выборочно/в чанках и/или использовать DEM локально.
 - Если вы не уверены в лимитах публичных сервисов — НЕ запускайте массовые запросы без
   контроля (risk of being rate-limited or blocked).
"""

import requests
import math
import numpy as np
import pandas as pd
from time import sleep

# --------------- НАСТРОЙКИ ---------------
START = (59.9311, 30.3609)   # Санкт-Петербург (lat, lon)
END   = (55.7558, 37.6173)   # Москва (lat, lon)
N_POINTS = 1000           # желаемое число точек
OSRM_URL = "https://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}"
# Для elevation: используем Open-Elevation POST (public) по умолчанию.
OPEN_ELEVATION_URL = "https://api.open-elevation.com/api/v1/lookup"
# Альтернатива: Open-Meteo elevation API (no key) - можно использовать по желанию.
OPEN_METEO_ELEVATION = "https://api.open-meteo.com/v1/elevation"  # docs: open-meteo.com

# Параметры batch для elevation (чтобы не перегрузить публичный сервис)
ELEVATION_BATCH = 100  # уменьшите, если видите ошибки или лимиты

# --------------- ВСПОМАГАТЕЛЬНЫЕ ФУНКЦИИ ---------------
def haversine_m(lat1, lon1, lat2, lon2):
    """Возвращает расстояние в метрах между двумя точками (WGS84) — формула Haversine."""
    R = 6371000.0  # радиус Земли в метрах
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2*R*math.asin(math.sqrt(a))

def osrm_get_route(start, end, overview='full'):
    """
    Запрашивает OSRM demo server маршрут между start и end.
    Возвращает список координат polyline в формате [(lat, lon), ...].
    """
    lat1, lon1 = start
    lat2, lon2 = end
    url = OSRM_URL.format(lon1=lon1, lat1=lat1, lon2=lon2, lat2=lat2)
    params = {
        "overview": overview,
        "geometries": "geojson"  # получаем geojson координаты
    }
    print("Запрос маршрута OSRM...")
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    js = r.json()
    # OSRM возвращает routes[0].geometry.coordinates как [ [lon, lat], ... ]
    coords_lonlat = js['routes'][0]['geometry']['coordinates']
    # конвертируем в (lat, lon)
    coords = [(pt[1], pt[0]) for pt in coords_lonlat]
    print(f"OSRM вернул {len(coords)} вершин маршрута.")
    return coords

def densify_along_path(coords, n_points):
    """
    Интерполирует полилинию coords (list (lat,lon)) равномерно по длине на n_points точек.
    Алгоритм:
      - считаем длины каждого сегмента и кумулятивную длину
      - для каждой целевой позиции d в linspace(0, total) находим сегмент и линейно интерполируем
    Возвращает массив shape (n_points, 2): [[lat, lon], ...]
    """
    # 1) длины сегментов
    seg_lengths = []
    for i in range(len(coords)-1):
        seg_lengths.append(haversine_m(coords[i][0], coords[i][1], coords[i+1][0], coords[i+1][1]))
    seg_lengths = np.array(seg_lengths)
    cum = np.concatenate(([0.0], np.cumsum(seg_lengths)))  # длина у каждой вершины
    total = cum[-1]
    print(f"Общая длина маршрута ≈ {total/1000:.2f} km")
    # 2) целевые расстояния
    targets = np.linspace(0, total, n_points)
    out = np.empty((n_points, 2), dtype=float)
    seg_i = 0
    for ti, d in enumerate(targets):
        # двигаем seg_i, пока d > cum[seg_i+1]
        while seg_i < len(seg_lengths)-1 and d > cum[seg_i+1]:
            seg_i += 1
        # позиции seg_i (вершина seg_i) и seg_i+1
        d0 = cum[seg_i]
        seg_len = seg_lengths[seg_i]
        if seg_len == 0:
            frac = 0.0
        else:
            frac = (d - d0) / seg_len
            frac = max(0.0, min(1.0, frac))
        lat0, lon0 = coords[seg_i]
        lat1, lon1 = coords[seg_i+1]
        lat = lat0 + (lat1 - lat0) * frac
        lon = lon0 + (lon1 - lon0) * frac
        out[ti, 0] = lat
        out[ti, 1] = lon
    return out, total

def get_elevations_open_elevation(points):
    """
    points: iterable of (lat, lon)
    Использует публичный Open-Elevation POST /api/v1/lookup с JSON {"locations":[{"latitude":..., "longitude":...},...]}
    Возвращает список высот в метрах по порядку. Делает batch-запросы размером ELEVATION_BATCH.
    ВНИМАНИЕ: публичный сервис имеет ограничения (обычно ~1000 req/month). Для 100k точек
    нужно либо хостить свой сервер, либо покупать платный план / использовать локальные DEM.
    """
    elevations = []
    url = OPEN_ELEVATION_URL
    points_list = list(points)
    n = len(points_list)
    print("Получаем высоты через Open-Elevation (batch).")
    for i in range(0, n, ELEVATION_BATCH):
        batch = points_list[i:i+ELEVATION_BATCH]
        payload = {"locations": [{"latitude": float(lat), "longitude": float(lon)} for lat, lon in batch]}
        try:
            r = requests.post(url, json=payload, timeout=30)
            r.raise_for_status()
            js = r.json()
            # results: list with elevation entries in same order
            batch_elev = [res.get("elevation", None) for res in js.get("results", [])]
            if len(batch_elev) != len(batch):
                print(f"Warning: batch response length mismatch at chunk {i//ELEVATION_BATCH}")
            elevations.extend(batch_elev)
        except Exception as e:
            print("Ошибка при запросе высот:", str(e))
            # Попробуем добавить Noneы и продолжить (или можно делать retry)
            elevations.extend([None]*len(batch))
        # чтобы не хвастать API — небольшая пауза (подберите под вашу политику использования)
        sleep(0.2)
    print(f"Получено высот: {len(elevations)}")
    return elevations

def compute_gradients(elevations, distances):
    """
    elevations: list of elevation (meters) (len = n)
    distances: array of cumulative distances от начала (meters) (len = n)
    Возвращает gradient для каждой точки в процентах (%) как (delta_h / delta_x) * 100
    gradient[0] = 0
    Если elevation == None — gradient = None
    """
    n = len(elevations)
    grads = [None]*n
    grads[0] = 0.0
    for i in range(1, n):
        e0 = elevations[i-1]
        e1 = elevations[i]
        if e0 is None or e1 is None:
            grads[i] = None
            continue
        dh = e1 - e0
        dx = distances[i] - distances[i-1]
        if dx == 0:
            grads[i] = 0.0
        else:
            grads[i] = (dh / dx) * 100.0  # percent
    return grads

# --------------- MAIN ---------------
def main():
    # 1) Получаем маршрут (вершины)
    coords = osrm_get_route(START, END, overview='full')

    # 2) Интерполируем до N_POINTS
    points_arr, total_len = densify_along_path(coords, N_POINTS)

    # 3) Соберём кумулятивные расстояния (нужны для градиента)
    dists = np.zeros(N_POINTS, dtype=float)
    for i in range(1, N_POINTS):
        dists[i] = dists[i-1] + haversine_m(points_arr[i-1,0], points_arr[i-1,1],
                                            points_arr[i,0], points_arr[i,1])

    # 4) Получаем высоты — осторожно с лимитами
    # Здесь по умолчанию используется Open-Elevation (публичный) — для 100k точек
    # это плохо: рекомендую сначала протестировать с N_POINTS=1000, обеспечить batch/pause,
    # или развернуть свой elevation сервер или использовать DEM локально.
    elevations = get_elevations_open_elevation([(lat, lon) for lat, lon in points_arr])

    # 5) Градиенты
    gradients = compute_gradients(elevations, dists)

    # 6) Собираем DataFrame и сохраняем CSV
    df = pd.DataFrame({
        "idx": np.arange(N_POINTS),
        "lat": points_arr[:,0],
        "lon": points_arr[:,1],
        "dist_m": dists,
        "elevation_m": elevations,
        "gradient_pct": gradients
    })
    out_csv = "route_piter_moskva_1000.csv"
    df.to_csv(out_csv, sep=';', index=False)
    print("Сохранено в", out_csv)
    print("Готово.")

if __name__ == "__main__":
    main()
