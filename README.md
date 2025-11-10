# Building_a_route_between_two_points_with_division_into-waypoints

Проект строит реальный дорожный маршрут (OSRM), интерполирует его в N точек (например 100 000), берёт высоты из локального DEM (SRTM) и генерирует CSV. Есть простая HTML-визуализация (Leaflet + canvas) для отображения маршрута и точек.

## Структура проекта
```
.
├─ build_route_100k_and_sample.py     # основной pipeline: запрос маршрута, densify, sample DEM -> CSV
├─ download_opentopo_srtm.py          # (опционально) скачивает SRTM (OpenTopography) по bbox
├─ inspect_tif.py                     # краткая проверка GeoTIFF (получаются через скрипт выше)
├─ sample_elev_local.py               # простой sampler: CSV(lat,lon) -> add elevation,gradient
├─ route_viewer.html                  # визуализатор CSV (Leaflet + canvas)
├─ route_piter_moskva_100k.csv        # пример выходного CSV (генерируется)
└─ README.md
```

## Что делает проект
1. Получение маршрута по дорогам
Локально (рекомендуется) через ваш собственный OSRM сервер (Docker) или временно — через публичный OSRM. Результат — полилиния маршрута (последовательность lat/lon).

2. Интерполяция (densify)
Полилиния равномерно разбивается по длине на N точек (например 100000).

3. Высоты из DEM (локально)
Для каждой точки батчами запрашиваем высоту из локального GeoTIFF (SRTM) при помощи rasterio.sample.

4. Расчёт градиента
На основе высот и расстояний между точками вычисляется градиент (в %).

5. CSV и визуализация
Выходной CSV содержит: idx, lat, lon, dist_m, elevation_m, gradient_pct. HTML-визуализатор отображает маршрут + точки (canvas).


## Готовность окружения (Windows 10, рекомендовано)\
  - Docker Desktop (с включённым WSL2) — для локального OSRM.
  - Miniconda / Anaconda — для Python окружения. [Miniconda](https://www.anaconda.com/docs/getting-started/miniconda/install)
  - Рекомендуемые ресурсы: 32 GB RAM / SSD желательно для больших PBF (Россия) и быстрой предобработки OSRM.


## Быстрый старт: создать Python окружение
Откройте Anaconda Prompt (или PowerShell, если conda инициализирован) и выполните:

```
conda create -n dem python=3.11 -y
conda activate dem
conda install -c conda-forge gdal rasterio numpy pandas tqdm -y
pip install requests polyline
```

Примечание: gdal устанавливает утилиты gdalbuildvrt, gdal_fillnodata.py и др. Если видите WinError 193 при вызове gdal_fillnodata.py — запускайте его через python gdal_fillnodata.py ... или используйте версию скрипта, где sys.executable применяется (в репозитории изменение уже учтено).

## Где взять исходные данные

- OSM PBF (карта) для OSRM: скачайте PBF для нужной области у Geofabrik (поиск Geofabrik download). Например файл russia-*.osm.pbf.
(Ищите download.geofabrik.de на сайте Geofabrik.) ( https://download.geofabrik.de/ )

- DEM (SRTM 1-arcsec / ~30 m): OpenTopography / USGS EarthData / CGIAR.
  - OpenTopography API можно использовать (требуется регистрация и API Key). [OpenTopography]( https://portal.opentopography.org/myopentopo )
  - CGIAR SRTM 90 m — если хотите более простую доступность (меньше регистраций), но хуже разрешение.



## Подготовка OSRM (Docker, Windows)

Положите russia-251109.osm.pbf (или нужный extract) в папку проекта, например OSRM_local/.

Выполните подготовку данных (PowerShell в этой папке):
```bush
# извлечение (osrm-extract)
docker run --rm -t -v ${PWD}:/data osrm/osrm-backend osrm-extract -p /opt/car.lua /data/russia-251109.osm.pbf

# если хотите MLD (для production) — используйте partition + customize
docker run --rm -t -v ${PWD}:/data osrm/osrm-backend osrm-partition /data/russia-251109.osrm
docker run --rm -t -v ${PWD}:/data osrm/osrm-backend osrm-customize /data/russia-251109.osrm

# для CH (contraction hierarchies)
docker run --rm -t -v ${PWD}:/data osrm/osrm-backend osrm-contract /data/russia-251109.osrm
```

Запуск роутера:

Если вы сделали osrm-contract (CH):
```bush
docker run -d --name osrm-ch -p 5000:5000 -v ${PWD}:/data osrm/osrm-backend osrm-routed --algorithm ch /data/russia-251109.osrm
```

Если вы сделали partition/customize (MLD):
```bush
docker run -d --name osrm-mld -p 5000:5000 -v ${PWD}:/data osrm/osrm-backend osrm-routed --algorithm mld /data/russia-251109.osrm
```

Тест (в PowerShell):
```
# проверка работы сервера (URL пример)
Invoke-WebRequest -Uri "http://localhost:5000/route/v1/driving/30.3609,59.9311;37.6173,55.7558?overview=false" -UseBasicParsing
```

Требования: во время osrm-extract/osrm-contract требуется запас по RAM и месту на диске. Для крупного PBF (Россия) — десятки гигабайт.


## Скачивание DEM (OpenTopography) — опционально
В репозитории есть скрипт ```download_opentopo_srtm.py```. Использование:
```
conda activate dem
pip install requests tqdm
python download_opentopo_srtm.py --input route_piter_moskva_1000.csv --api-key YOUR_OPENTOP_KEY --out-prefix srtm_piter_moskva --buffer 0.05
```
- Скрипт вычислит bbox по входному CSV и попробует скачать GeoTIFF (или ZIP) из OpenTopography, распакует и при необходимости запустит gdal_fillnodata.py (интерполяция void).
- Важное: OpenTopography использует квоты/лимиты — проверяйте ключ и панель управления.
Если вы уже скачали DEM вручную (файл .tif), просто поместите его в папку проекта и укажите путь при запуске скриптов.

## Генерация CSV с 100k точек (локально, полный pipeline)
1. Убедитесь, что OSRM сервер поднят и доступен по http://localhost:5000.
2. Пример запуска (тест 1k точек):
```
conda activate dem
python build_route_100k_and_sample.py \
  --start_lat 59.931101 --start_lon 30.360892 \
  --end_lat 55.7558 --end_lon 37.6173 \
  --osrm_url "http://localhost:5000/route/v1/driving/{lon1},{lat1};{lon2},{lat2}" \
  --dem appRasterSelectAPIService1762742803327961404667.tif \
  --out route_test_1k.csv --n 1000 --batch 20000
```
3. Если тест прошёл — запустите --n 100000 (и, например, --batch 50000):
```
python build_route_100k_and_sample.py ... --out route_piter_moskva_100k.csv --n 100000 --batch 50000
```
Пояснения опций:
 - --n — количество итоговых точек.
 - --batch — сколько точек отдавать rasterio.sample за раз (регулируйте по доступной памяти).
 - Скрипт автоматически делает fallback (разбивает запрос на сегменты), игнорирует системные прокси (чтобы локальный requests шел на localhost напрямую), декодирует polyline и т.д.


 ## Визуализация (route_viewer.html)
 1. Положите ```route_piter_moskva_100k.csv``` рядом с ```route_viewer.html```.
 2. Запустите локальный HTTP сервер (нужен, потому что браузер блокирует fetch из file://):
 ```
 # в папке с HTML
python -m http.server 8000
# затем откройте в браузере:
# http://localhost:8000/route_viewer.html
```

3. Как поменять точки, которые рисуются
  - На уровне кода: измените аргументы --start_lat, --start_lon, --end_lat, --end_lon при запуске build_route_100k_and_sample.py, затем пересоздайте CSV.
  - В HTML: viewer читает CSV и рендерит его; чтобы нарисовать другой маршрут — сгенерируйте CSV для новых точек и перезагрузите страницу.

4. Поведение полилиний/точек: в HTML сделана оптимизация — на низких зумах отображается синяя полилиния, на больших — скрывается polyline и остаётся canvas с точками (чтобы не было эффекта «двойной линии»). Порог и стиль можно поменять прямо в route_viewer.html


## Частые проблемы и их исправления
  - ```conda activate dem``` не работает — выполните ```conda init powershell```, закройте и откройте PowerShell или используйте Anaconda Prompt.
  - ```gdal_fillnodata.py``` выдаёт WinError 193 — запускайте через интерпретатор: ```python C:\path\to\gdal_fillnodata.py ...``` или используйте версию скрипта, где запускается через ```sys.executable```.
  - OSRM возвращает 502 — возможные причины:
    - requests идёт через системный прокси: у вас в окружении задан HTTP_PROXY/HTTPS_PROXY. Скрипты здесь создают requests.Session() с trust_env=False, чтобы игнорировать прокси при обращении к localhost.
    - Контейнер падает из-за OOM: проверьте логи docker logs -f osrm-ch и увеличьте доступную память Docker Desktop или используйте меньше потоков.
    - Большие запросы по геометрии: pipeline делает fallback — разбивает запрос на сегменты.
  - ```netstat -ano | findstr ":5000"``` проверка, что порт не занят
  - Если пишет, что контейнер уже запущен то ```docker ps -a``` показывает список всех активных (в иделе ничего не должно быть), а ```docker ps -aq | ForEach-Object { docker rm -f $_ }``` удалить все неактивные, в вашем случае, если есть другие контейнеры, то следует удалять только новые из списка.
  - CSV в Excel открывается в одном столбце — Excel в русской локали ожидает ; разделитель; сохраните CSV в .xlsx или to_csv(..., sep=';'). (тут это можно не делать, он так работает)
  - Очень большие файлы DEM / PBF — убедитесь, что у вас есть свободное место (десятки GB) и RAM.


## прочее
Примерный список файлов, что у вас должен быть для запуска локальной OSRM
```
Name                                           Length
----                                           ------
russia-251109.osm.pbf                      3984323725
russia-251109.osrm                         1910668288
russia-251109.osrm.cells                     13187584
russia-251109.osrm.cell_metrics            1127777280
russia-251109.osrm.cnbg                     174369280
russia-251109.osrm.cnbg_to_ebg              174369280
russia-251109.osrm.datasource_names             69632
russia-251109.osrm.ebg                     1007006208
russia-251109.osrm.ebg_nodes                257946112
russia-251109.osrm.edges                    293720576
russia-251109.osrm.enw                      256260608
russia-251109.osrm.fileIndex                791953560
russia-251109.osrm.geometry                 902334464
russia-251109.osrm.icd                      149700608
russia-251109.osrm.maneuver_overrides            5120
russia-251109.osrm.mldgr                   1041273344
russia-251109.osrm.names                      7058432
russia-251109.osrm.nbg_nodes                457654784
russia-251109.osrm.partition                170876416
russia-251109.osrm.properties                    6144
russia-251109.osrm.ramIndex                   3161088
russia-251109.osrm.restrictions                  4096
russia-251109.osrm.timestamp                     3584
russia-251109.osrm.tld                           8704
russia-251109.osrm.tls                          16384
russia-251109.osrm.turn_duration_penalties   83920384
russia-251109.osrm.turn_penalties_index     503502848
russia-251109.osrm.turn_weight_penalties     83920384
```
