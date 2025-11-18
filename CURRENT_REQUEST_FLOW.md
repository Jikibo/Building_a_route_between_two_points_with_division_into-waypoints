# 🔄 Текущий путь запроса (с симуляцией)

## Обзор системы

```
Браузер (index.html) ←→ Flask (server.py) ←→ Python скрипт ←→ OSRM
                                                    ↓
                                                   DEM
```

---

## Полный цикл работы

### Этап 1: Загрузка страницы

**1.1. Пользователь открывает http://localhost:8001**

```
GET / → Flask → index.html
```

**1.2. Браузер загружает ресурсы**

```javascript
// Автоматически загружаются:
- Leaflet.js (карта)
- Chart.js (графики)
- index.html (интерфейс)
```

**1.3. Инициализация при загрузке**

```javascript
window.addEventListener('load', function() {
    loadVehicleData();  // Загрузка параметров ТС
    initCharts();       // Инициализация графиков
});
```

---

### Этап 2: Загрузка данных ТС

**2.1. Запрос данных ТС**

```javascript
const response = await fetch('/vehicle_data.json');
```

**2.2. Flask отдает файл**

```python
@app.route('/vehicle_data.json')
def vehicle_data():
    return send_from_directory('.', 'vehicle_data.json')
```

**2.3. Обновление UI**

```javascript
vehicleData = await response.json();

document.getElementById('vehicleMass').textContent = 
    vehicleData.vehicle.vehicle_mass_kg + ' кг';
// ... остальные параметры
```

**Результат:**
- Параметры ТС отображаются в боковой панели
- Данные доступны для расчетов

---

### Этап 3: Геокодирование адресов

**3.1. Пользователь вводит "Москва"**

```javascript
geocodeStart() → fetch('http://localhost:8001/geocode', {
    method: 'POST',
    body: JSON.stringify({ address: "Москва" })
})
```

**3.2. Flask обрабатывает запрос**

```python
@app.route('/geocode', methods=['POST'])
def geocode():
    address = request.get_json()['address']
    coords = geocode_address(address)  # Запрос к Nominatim
    return jsonify({'lat': lat, 'lon': lon})
```

**3.3. Nominatim API**

```python
response = requests.get(
    'https://nominatim.openstreetmap.org/search',
    params={'q': 'Москва', 'format': 'json'}
)
# Возвращает: {'lat': '55.7558', 'lon': '37.6173'}
```

**3.4. Создание маркера**

```javascript
startMarker = L.marker([55.7558, 37.6173], {
    draggable: true  // Можно перемещать
}).addTo(map);
```

**Повторяется для конечной точки**

---

### Этап 4: Построение маршрута

**4.1. Пользователь нажимает "Построить маршрут"**

```javascript
buildRoute() → fetch('http://localhost:8001/build_route', {
    method: 'POST',
    body: JSON.stringify({
        start_lat: 55.7558,
        start_lon: 37.6173,
        end_lat: 56.1366,
        end_lon: 40.4093,
        n_points: 100000
    })
})
```

**4.2. Flask проверяет кэш**

```python
output_csv = f'route_{start_lat:.4f}_{start_lon:.4f}_to_{end_lat:.4f}_{end_lon:.4f}.csv'

if os.path.exists(output_csv):
    print("Маршрут уже существует")
    # Пропускаем генерацию
else:
    # Генерируем новый маршрут
```

**4.3. Проверка OSRM**

```python
try:
    test_response = requests.get('http://localhost:5000/...')
    if test_response.status_code == 200:
        osrm_url = 'http://localhost:5000/...'  # Локальный
    else:
        raise Exception()
except:
    osrm_url = 'http://router.project-osrm.org/...'  # Публичный
```

**4.4. Запуск Python скрипта**

```python
cmd = [
    'python', 'build_route_100k_and_sample.py',
    '--start_lat', '55.7558',
    '--start_lon', '37.6173',
    '--end_lat', '56.1366',
    '--end_lon', '40.4093',
    '--osrm_url', osrm_url,
    '--dem', 'appRasterSelectAPIService1762742803327961404667.tif',
    '--out', output_csv,
    '--n', '100000',
    '--batch', '50000'
]

result = subprocess.run(cmd, capture_output=True, timeout=300)
```

**4.5. Python скрипт генерирует маршрут**

```python
# 1. Запрос к OSRM
coords = get_route_with_fallback(osrm_url, start, end)
# Возвращает ~3000 точек (вершины дорожного графа)

# 2. Интерполяция
pts, total_len = densify_along_path(coords, 100000)
# Создает 100,000 равномерно распределенных точек

# 3. Получение высот
elevs = sample_elevations_rasterio(dem_path, pts, batch=50000)
# Запрашивает высоты из GeoTIFF

# 4. Расчет градиентов
grads = compute_gradients(elevs, dists)
# Вычисляет уклон между точками

# 5. Сохранение CSV
df.to_csv(output_csv)
```

**4.6. Flask читает CSV**

```python
df = pd.read_csv(output_csv)

# Создает 4 уровня детализации
levels = {
    'full': df,              # 100,000 точек
    'high': df.iloc[::10],   # 10,000 точек
    'medium': df.iloc[::100],# 1,000 точек
    'low': df.iloc[::1000]   # 100 точек
}

# Преобразует в GeoJSON
for level_name, level_df in levels.items():
    geojson_levels[level_name] = create_geojson(level_df)

# Получает общее расстояние
total_distance = float(df.iloc[-1]['dist_m'])

return jsonify({
    'success': True,
    'total_points': len(df),
    'total_distance': total_distance,
    'levels': geojson_levels
})
```

**4.7. Браузер получает данные**

```javascript
const data = await response.json();

// Создает слои для каждого уровня
Object.keys(data.levels).forEach(levelName => {
    routeLayers[levelName] = L.geoJSON(data.levels[levelName], {
        pointToLayer: function(feature, latlng) {
            return L.circleMarker(latlng, {...});
        }
    });
});

// Сохраняет точки для симуляции
routePoints = data.levels.full.features.map(f => ({
    lat: f.geometry.coordinates[1],
    lon: f.geometry.coordinates[0],
    elevation: f.properties.elevation,
    gradient: f.properties.gradient,
    dist_m: f.properties.idx * (data.total_distance / data.total_points)
}));

// Обновляет графики (сохраняет полные данные)
updateChartsWithRoute(data);

// Показывает маршрут
updateRouteVisibility();
```

---

### Этап 5: Симуляция движения

**5.1. Пользователь нажимает "Старт"**

```javascript
startSimulation() {
    // Создает маркер ТС
    vehicleMarker = L.marker([startPoint.lat, startPoint.lon], {
        icon: L.divIcon({...})
    }).addTo(map);
    
    // Создает линию пройденного пути
    traveledPath = L.polyline([], {
        color: '#27ae60'
    }).addTo(map);
    
    // Запускает таймер
    simulationInterval = setInterval(updateSimulation, 100);
}
```

**5.2. Обновление каждые 100мс**

```javascript
function updateSimulation() {
    // 1. Получаем текущую точку
    const currentPoint = routePoints[currentPointIndex];
    const gradient = currentPoint.gradient || 0;
    
    // 2. Рассчитываем целевую скорость
    let targetSpeed = calculateTargetSpeed(gradient);
    
    // 3. Плавно меняем скорость
    if (currentSpeed < targetSpeed) {
        currentSpeed += acceleration * 0.1;
    } else {
        currentSpeed -= deceleration * 0.1;
    }
    
    // 4. Рассчитываем пройденное расстояние
    const distancePerUpdate = (currentSpeed / 3600) * 0.1 * timeMultiplier;
    const targetDistance = currentPoint.dist_m + distancePerUpdate * 1000;
    
    // 5. Находим следующую точку
    while (routePoints[nextIndex].dist_m < targetDistance) {
        nextIndex++;
    }
    currentPointIndex = nextIndex;
    
    // 6. Обновляем позицию маркера
    vehicleMarker.setLatLng([newPoint.lat, newPoint.lon]);
    
    // 7. Обновляем пройденный путь
    traveledPath.addLatLng([newPoint.lat, newPoint.lon]);
    
    // 8. Рассчитываем показатели
    const virtualTime = distanceKm / currentSpeed * 3600;
    const consumption = calculateCurrentConsumption(currentSpeed, gradient);
    const optimal = calculateOptimalSpeed(gradient, currentSpeed);
    
    // 9. Обновляем графики
    speedHistory.push(currentSpeed);
    speedChart.update('none');
    
    const progressPercent = currentPointIndex / routePoints.length;
    elevationChart.data.datasets[0].data = 
        elevationChart.data.datasets[0].fullData.slice(0, chartPointsToShow);
    elevationChart.update('none');
    
    // 10. Обновляем UI
    document.getElementById('currentSpeed').textContent = currentSpeed + ' км/ч';
    document.getElementById('travelTime').textContent = formatTime(virtualTime);
    document.getElementById('currentConsumption').textContent = consumption + ' л/100км';
    // ... остальные показатели
}
```

---

## Поток данных

### Построение маршрута

```
Пользователь
    ↓ (вводит адреса)
Браузер
    ↓ (POST /geocode)
Flask
    ↓ (GET Nominatim)
Nominatim API
    ↓ (координаты)
Flask
    ↓ (JSON)
Браузер
    ↓ (создает маркеры)
Leaflet карта
    ↓ (пользователь нажимает "Построить")
Браузер
    ↓ (POST /build_route)
Flask
    ↓ (subprocess)
Python скрипт
    ↓ (GET /route)
OSRM
    ↓ (polyline ~3000 точек)
Python скрипт
    ↓ (densify)
100,000 точек
    ↓ (sample)
DEM (GeoTIFF)
    ↓ (высоты)
Python скрипт
    ↓ (градиенты)
CSV файл
    ↓ (read)
Flask
    ↓ (GeoJSON 4 уровня)
Браузер
    ↓ (создает слои)
Leaflet карта
```

### Симуляция движения

```
Пользователь
    ↓ (нажимает "Старт")
Браузер
    ↓ (setInterval 100мс)
updateSimulation()
    ↓ (читает routePoints)
Расчет скорости
    ↓ (на основе уклона)
Расчет расстояния
    ↓ (на основе скорости)
Поиск следующей точки
    ↓ (в массиве routePoints)
Обновление маркера
    ↓ (Leaflet)
Обновление графиков
    ↓ (Chart.js)
Обновление UI
    ↓ (DOM)
Браузер
    ↓ (отображение)
Пользователь видит анимацию
```

---

## Ключевые моменты

### 1. Кэширование

**Где:** Flask проверяет существование CSV файла

**Зачем:** Не пересчитывать одинаковые маршруты

**Как:** По имени файла с координатами

### 2. Уровни детализации

**Где:** Flask создает 4 уровня при чтении CSV

**Зачем:** Кластеризация для производительности

**Уровни:**
- full: 100,000 точек (zoom 15+)
- high: 10,000 точек (zoom 12-14)
- medium: 1,000 точек (zoom 9-11)
- low: 100 точек (zoom 0-8)

### 3. Реальное время

**Где:** updateSimulation() каждые 100мс

**Как:** Расчет пройденного расстояния на основе скорости

**Формула:** `distance = (speed / 3600) * 0.1 * multiplier`

### 4. Накопление графиков

**Где:** updateSimulation() обновляет графики

**Как:** Показывает только пройденную часть

**Данные:** Полные данные в `fullData`, видимые в `data`

---

## Производительность

### Узкие места

1. **Генерация маршрута:** 3-5 минут
   - OSRM: 1-3 сек
   - Интерполяция: 1-2 сек
   - DEM sampling: 2-4 мин ⚠️
   - Градиенты: <1 сек

2. **Передача GeoJSON:** 2-5 сек
   - Размер: ~10 MB
   - 4 уровня детализации

3. **Симуляция:** 10 FPS
   - Обновление каждые 100мс
   - CPU: 5-10%

### Оптимизации

1. **Кэширование CSV** - не пересчитывать
2. **Батчинг DEM** - по 50,000 точек
3. **Кластеризация** - 4 уровня детализации
4. **Накопление графиков** - slice вместо пересоздания
5. **Пройденный путь** - каждая 10-я точка

---

**Система работает эффективно и масштабируемо!** 🚀
