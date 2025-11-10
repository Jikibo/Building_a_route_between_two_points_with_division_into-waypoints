# inspect_tif.py
import rasterio
import numpy as np
p = r"C:\Users\Home3\PyCharmMiscProject\appRasterSelectAPIService1762742803327961404667.tif"
with rasterio.open(p) as ds:
    arr = ds.read(1, masked=True)  # masked array
    print("CRS:", ds.crs)
    print("Bounds:", ds.bounds)
    print("Shape:", arr.shape)
    print("dtype:", arr.dtype)
    print("nodata:", ds.nodatavals)
    print("count valid pixels:", (~arr.mask).sum())
    if (~arr.mask).sum() > 0:
        print("min,max,mean (valid):", float(arr.min()), float(arr.max()), float(arr.mean()))
    else:
        print("Нет валидных пикселей (все nodata?)")