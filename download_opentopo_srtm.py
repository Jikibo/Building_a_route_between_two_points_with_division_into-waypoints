"""
download_opentopo_srtm.py

Скачивает SRTM 1-arcsec (GL1, ~30m) из OpenTopography для bbox, вычисленного по CSV с колонками lat,lon.
Параметры: input_csv, api_key, out_prefix (опционально), buffer_deg (опционально, по умолчанию 0.05 deg)

Запуск (Anaconda Prompt):
python download_opentopo_srtm.py --input route_piter_moskva_1000.csv --api-key 1b846ed1c955c461bdca8668e259f294

Требования (в Conda env 'dem'):
pip install requests tqdm
gdal и gdal_fillnodata.py должны быть доступны (вы устанавливали через conda-forge).
"""
import os
import sys
import argparse
import requests
from tqdm import tqdm
import zipfile
import subprocess
import shutil
import pandas as pd
import shlex

# --- Конфиг / fallback endpoints ---
OT_BASES = [
    "https://portal.opentopography.org/API/globaldem"
]
DEMTYPE = "SRTMGL1"   # SRTM Global 30m
OUTPUT_FORMAT = "GTiff"

# --- Вспомогательные функции ---
def compute_bbox_from_csv(csv_path, buffer_deg=0.05):
    df = pd.read_csv(csv_path)
    if not {'lat','lon'}.issubset(df.columns):
        raise SystemExit("Входной CSV должен содержать столбцы 'lat' и 'lon'.")
    lat_min = df['lat'].min()
    lat_max = df['lat'].max()
    lon_min = df['lon'].min()
    lon_max = df['lon'].max()
    # применяем буфер
    south = float(lat_min) - buffer_deg
    north = float(lat_max) + buffer_deg
    west  = float(lon_min) - buffer_deg
    east  = float(lon_max) + buffer_deg
    # нормализация (на всякий случай)
    if west < -180: west = -180
    if east > 180: east = 180
    if south < -90: south = -90
    if north > 90: north = 90
    return south, north, west, east

def try_download(url, params, out_path):
    print(f"Попытка: {url}  params={params}")
    try:
        with requests.get(url, params=params, stream=True, timeout=300) as r:
            if r.status_code != 200:
                print(f"  => HTTP {r.status_code}")
                # если сервис вернул HTML с ошибкой — выведем (коротко)
                text = r.text
                print("  Ответ сервера (первые 512 символов):")
                print(text[:512])
                return False
            # Пробуем получить filename из заголовка
            cd = r.headers.get('content-disposition', '')
            fname = None
            if 'filename=' in cd:
                fname = cd.split('filename=')[-1].strip().strip('"')
            if fname is None:
                # попробуем расширение по content-type
                ct = r.headers.get('content-type','')
                if 'zip' in ct or 'application/octet-stream' in ct:
                    fname = out_path + ".zip"
                else:
                    fname = out_path
            # сохраняем потоково
            total = r.headers.get('content-length')
            total = int(total) if total and total.isdigit() else None
            save_path = fname if os.path.isabs(fname) else os.path.join(os.getcwd(), fname)
            print(f"  Сохраняю в: {save_path}")
            with open(save_path, "wb") as f, tqdm(total=total, unit='B', unit_scale=True, desc='download') as pbar:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        pbar.update(len(chunk))
            return save_path
    except Exception as e:
        print("  Ошибка запроса:", e)
        return False

def unpack_if_zip(path):
    if path is False:
        return None
    if not os.path.exists(path):
        return None
    if zipfile.is_zipfile(path):
        outdir = os.path.splitext(path)[0] + "_unzipped"
        os.makedirs(outdir, exist_ok=True)
        print(f"  Распаковываю {path} -> {outdir}")
        with zipfile.ZipFile(path, 'r') as z:
            z.extractall(outdir)
        # пытаемся найти .tif внутри
        for root, _, files in os.walk(outdir):
            for fn in files:
                if fn.lower().endswith('.tif') or fn.lower().endswith('.tiff'):
                    return os.path.join(root, fn)
        return outdir  # если .tif внутри не найден, возвращаем папку
    else:
        # если не zip — возможно сразу GeoTIFF
        if path.lower().endswith('.tif') or path.lower().endswith('.tiff'):
            return path
        # если имя без расширения, ищем .tif рядом
        if os.path.exists(path):
            return path
        return None

def run_gdal_fillnodata(input_tif, out_tif, md=100, si=2):
    """Запускает gdal_fillnodata.py через текущий Python (sys.executable) — Windows-safe."""
    # На Windows лучше вызывать сам .py через интерпретатор, чтобы избежать WinError 193
    # Попытаемся найти скрипт gdal_fillnodata.py в PATH; если не найдем, вызовем "gdal_fillnodata.py" как аргумент python.
    cmd_list = [
        sys.executable,
        "-m", "gdalfillnodata",  # try module entrypoint (works if gdal встроил модуль)
        "-md", str(md),
        "-si", str(si),
        "-of", "GTiff",
        input_tif,
        out_tif
    ]

    # Если модуль не найден, fallback: вызвать скрипт напрямую через "gdal_fillnodata.py" в PATH
    try:
        print("Попытка запустить gdal_fillnodata как модуль: ", " ".join(shlex.quote(x) for x in cmd_list))
        p = subprocess.run(cmd_list, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        print(p.stdout)
        return True
    except subprocess.CalledProcessError as e_mod:
        print("Запуск как модуль вернул ошибку; пробуем fallback через скрипт в PATH.")
        # fallback: python <path_to_script> ... — надеемся, что gdal_fillnodata.py доступен в PATH
        fallback_cmd = [sys.executable, "gdal_fillnodata.py", "-md", str(md), "-si", str(si), "-of", "GTiff", input_tif, out_tif]
        try:
            print("Fallback:", " ".join(shlex.quote(x) for x in fallback_cmd))
            p2 = subprocess.run(fallback_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            print(p2.stdout)
            return True
        except subprocess.CalledProcessError as e2:
            print("Fallback тоже вернул ошибку:")
            print(e2.stdout)
            print(e2.stderr)
            return False
        except FileNotFoundError:
            print("gdal_fillnodata.py не найден в PATH — убедитесь, что GDAL установлен и gdal_fillnodata.py доступен.")
            return False
    except FileNotFoundError as fe:
        print("Не найден модуль/скрипт для запуска gdal_fillnodata:", fe)
        return False

# --- Основной workflow ---
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", "-i", required=True, help="CSV с lat,lon")
    parser.add_argument("--api-key", "-k", required=True, help="OpenTopography API Key")
    parser.add_argument("--out-prefix", "-o", default="opentopo_srtm", help="Префикс для выходных файлов")
    parser.add_argument("--buffer", "-b", type=float, default=0.05, help="Buffer degrees вокруг bbox (по умолчанию 0.05)")
    parser.add_argument("--md", type=int, default=100, help="gdal_fillnodata max distance pixels")
    parser.add_argument("--si", type=int, default=2, help="gdal_fillnodata smoothing iterations")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print("Ошибка: входной CSV не найден:", args.input)
        sys.exit(1)

    south, north, west, east = compute_bbox_from_csv(args.input, buffer_deg=args.buffer)
    print("bbox (south,north,west,east):", south, north, west, east)

    params = {
        "demtype": DEMTYPE,
        "south": str(south),
        "north": str(north),
        "west": str(west),
        "east": str(east),
        "outputFormat": OUTPUT_FORMAT,
        "API_Key": args.api_key
    }

    out_basename = args.out_prefix + "_raw"
    saved = None
    for base in OT_BASES:
        res = try_download(base, params, out_basename)
        if res and res is not False:
            saved = res
            break
    if not saved:
        print("Не удалось скачать DEM с OpenTopography (попробуйте снова позже или вручную через портал).")
        sys.exit(1)

    # если скачали zip — распаковываем, иначе получаем путь к tif
    tif_path = unpack_if_zip(saved)
    if tif_path is None:
        print("Не удалось определить TIFF внутри ответа сервера.")
        sys.exit(1)
    print("Найден/получен TIFF:", tif_path)

    # создаём заполненную версию
    out_filled = args.out_prefix + "_filled.tif"
    ok = run_gdal_fillnodata(tif_path, out_filled, md=args.md, si=args.si)
    if not ok:
        print("gdal_fillnodata не прошёл. Вы всё равно можете вручную открыть", tif_path)
        sys.exit(1)

    print("Готово. Итоговый заполненный DEM:", out_filled)
    print("Далее можно использовать этот файл в rasterio/gdal для sample() и дальнейшей обработки.")
    return

if __name__ == "__main__":
    main()
