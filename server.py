# server.py
# Flask сервер для обработки запросов на построение маршрута
import os
import subprocess
import json
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import pandas as pd
import requests

app = Flask(__name__)
CORS(app)  # Разрешаем CORS для локальной разработки

# Nominatim для геокодирования адресов в координаты
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

def geocode_address(address):
    """
    Преобразует адрес в координаты через Nominatim API
    Возвращает (lat, lon) или None если не найдено
    """
    try:
        params = {
            'q': address,
            'format': 'json',
            'limit': 1
        }
        headers = {
            'User-Agent': 'RouteBuilder/1.0'  # Nominatim требует User-Agent
        }
        response = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data and len(data) > 0:
            lat = float(data[0]['lat'])
            lon = float(data[0]['lon'])
            return lat, lon
        return None
    except Exception as e:
        print(f"Geocoding error: {e}")
        return None

@app.route('/')
def index():
    """Главная страница - отдаем новый HTML интерфейс"""
    return send_from_directory('.', 'index.html')

@app.route('/vehicle_data.json')
def vehicle_data():
    """Отдаем данные ТС"""
    return send_from_directory('.', 'vehicle_data.json')

@app.route('/geocode', methods=['POST'])
def geocode():
    """
    Эндпоинт для геокодирования адреса
    Принимает JSON: {"address": "Санкт-Петербург"}
    Возвращает: {"lat": 59.93, "lon": 30.36} или {"error": "..."}
    """
    data = request.get_json()
    address = data.get('address', '').strip()
    
    if not address:
        return jsonify({'error': 'Адрес не указан'}), 400
    
    coords = geocode_address(address)
    if coords:
        lat, lon = coords
        return jsonify({'lat': lat, 'lon': lon, 'address': address})
    else:
        return jsonify({'error': f'Не удалось найти адрес: {address}'}), 404

@app.route('/build_route', methods=['POST'])
def build_route():
    """
    Эндпоинт для построения маршрута
    Принимает JSON: {
        "start_lat": 59.93, "start_lon": 30.36,
        "end_lat": 55.75, "end_lon": 37.61,
        "n_points": 100000
    }
    Запускает Python скрипт для генерации CSV
    Возвращает упрощенный GeoJSON для отображения
    """
    data = request.get_json()
    
    # Валидация входных данных
    try:
        start_lat = float(data['start_lat'])
        start_lon = float(data['start_lon'])
        end_lat = float(data['end_lat'])
        end_lon = float(data['end_lon'])
        n_points = int(data.get('n_points', 100000))
    except (KeyError, ValueError) as e:
        return jsonify({'error': f'Неверные параметры: {e}'}), 400
    
    # Имя выходного файла
    output_csv = f'route_{start_lat:.4f}_{start_lon:.4f}_to_{end_lat:.4f}_{end_lon:.4f}.csv'
    
    # Проверяем, существует ли уже такой маршрут
    if os.path.exists(output_csv):
        print(f"Маршрут уже существует: {output_csv}")
    else:
        # Проверяем доступность локального OSRM
        osrm_url = 'http://localhost:5000/route/v1/driving/{lon1},{lat1};{lon2},{lat2}'
        try:
            test_response = requests.get('http://localhost:5000/route/v1/driving/30.3609,59.9311;37.6173,55.7558?overview=false', timeout=2)
            if test_response.status_code != 200:
                raise Exception("OSRM не отвечает")
            print("Используется локальный OSRM")
        except Exception as e:
            print(f"Локальный OSRM недоступен ({e}), используется публичный сервер")
            osrm_url = 'http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}'
        
        # Запускаем скрипт генерации маршрута
        print(f"Генерация маршрута: {output_csv}")
        cmd = [
            'python', 'build_route_100k_and_sample.py',
            '--start_lat', str(start_lat),
            '--start_lon', str(start_lon),
            '--end_lat', str(end_lat),
            '--end_lon', str(end_lon),
            '--osrm_url', osrm_url,
            '--dem', 'appRasterSelectAPIService1762742803327961404667.tif',
            '--out', output_csv,
            '--n', str(n_points),
            '--batch', '50000'
        ]
        
        try:
            # Запускаем процесс и ждем завершения
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode != 0:
                error_msg = result.stderr or result.stdout
                print(f"Ошибка генерации: {error_msg}")
                return jsonify({'error': f'Ошибка генерации маршрута: {error_msg}'}), 500
                
            print("Маршрут успешно сгенерирован")
        except subprocess.TimeoutExpired:
            return jsonify({'error': 'Превышено время ожидания генерации маршрута'}), 500
        except Exception as e:
            return jsonify({'error': f'Ошибка запуска генерации: {str(e)}'}), 500
    
    # Читаем CSV и создаем упрощенный GeoJSON для разных уровней детализации
    try:
        df = pd.read_csv(output_csv)
        
        # Создаем несколько уровней детализации для кластеризации
        levels = {
            'full': df,  # Все точки
            'high': df.iloc[::10],  # Каждая 10-я точка
            'medium': df.iloc[::100],  # Каждая 100-я точка
            'low': df.iloc[::1000]  # Каждая 1000-я точка
        }
        
        geojson_levels = {}
        for level_name, level_df in levels.items():
            features = []
            for _, row in level_df.iterrows():
                features.append({
                    'type': 'Feature',
                    'geometry': {
                        'type': 'Point',
                        'coordinates': [row['lon'], row['lat']]
                    },
                    'properties': {
                        'idx': int(row['idx']),
                        'elevation': float(row['elevation_m']) if pd.notna(row['elevation_m']) else None,
                        'gradient': float(row['gradient_pct']) if pd.notna(row['gradient_pct']) else None
                    }
                })
            
            geojson_levels[level_name] = {
                'type': 'FeatureCollection',
                'features': features
            }
        
        # Получаем общее расстояние (последняя точка содержит накопленное расстояние)
        total_distance = float(df.iloc[-1]['dist_m']) if len(df) > 0 and 'dist_m' in df.columns else 0
        
        return jsonify({
            'success': True,
            'filename': output_csv,
            'total_points': len(df),
            'total_distance': total_distance,  # Расстояние в метрах
            'levels': geojson_levels
        })
        
    except Exception as e:
        return jsonify({'error': f'Ошибка чтения CSV: {str(e)}'}), 500

if __name__ == '__main__':
    # Запускаем сервер на порту 8001
    print("Запуск Flask сервера на http://localhost:8001")
    print("OSRM должен быть доступен на http://localhost:5000")
    app.run(host='0.0.0.0', port=8001, debug=False)
