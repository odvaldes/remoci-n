"""Consultas remotas optativas de capas públicas; no sustituyen cartografía oficial.

Copernicus DEM GLO-30: AWS Open Data (COG). ESA WorldCover: Microsoft
Planetary Computer STAC. El servidor Streamlit necesita acceso a Internet.
"""
from __future__ import annotations

import math
import os
from contextlib import ExitStack
from collections import Counter

import numpy as np
import rasterio
from rasterio.merge import merge
from rasterio.io import MemoryFile
from rasterio.mask import mask
from rasterio.warp import transform_geom
from shapely.geometry import mapping

DEM_ROOT = 'https://copernicus-dem-30m.s3.amazonaws.com'
STAC_URL = 'https://planetarycomputer.microsoft.com/api/stac/v1'
WORLDCOVER_CLASSES = {
    10: 'Árboles', 20: 'Arbustos', 30: 'Pastizales', 40: 'Cultivos',
    50: 'Construido', 60: 'Suelo desnudo / vegetación escasa',
    70: 'Nieve / hielo', 80: 'Agua permanente', 90: 'Humedal herbáceo',
    95: 'Manglar', 100: 'Musgos / líquenes',
}


def _tile_url(lat: int, lon: int) -> str:
    ns = 'N' if lat >= 0 else 'S'
    ew = 'E' if lon >= 0 else 'W'
    name = f'Copernicus_DSM_COG_10_{ns}{abs(lat):02d}_00_{ew}{abs(lon):03d}_00_DEM'
    return f'{DEM_ROOT}/{name}/{name}.tif'


def _bounds_with_context(polygon, context_km=1.0):
    # Aproximación para elegir teselas. La geometría original se conserva para los cálculos.
    xmin, ymin, xmax, ymax = polygon.bounds
    lat = (ymin + ymax) / 2
    dy = context_km / 111.0
    dx = context_km / max(20.0, 111.0 * math.cos(math.radians(lat)))
    return xmin-dx, ymin-dy, xmax+dx, ymax+dy


def _validate_area(polygon, max_extent_km=18):
    xmin, ymin, xmax, ymax = polygon.bounds
    width = (xmax-xmin)*111*max(0.1, math.cos(math.radians((ymin+ymax)/2)))
    height = (ymax-ymin)*111
    if max(width, height) > max_extent_km:
        raise ValueError(f'El polígono supera {max_extent_km} km de extensión. Divídelo para limitar las consultas remotas.')


def copernicus_dem_bytes(polygon, context_km=0.5):
    """Lee COG remotos y devuelve un GeoTIFF recortado a la extensión + contexto.

    No descarga un DEM nacional. Dependiendo de la caché HTTP, GDAL puede
    transferir partes de las teselas remotas. Máximo 4 teselas de 1°.
    """
    _validate_area(polygon)
    bounds = _bounds_with_context(polygon, context_km)
    x0, y0, x1, y1 = bounds
    tiles = [(la, lo) for la in range(math.floor(y0), math.floor(y1)+1)
                      for lo in range(math.floor(x0), math.floor(x1)+1)]
    if len(tiles) > 4:
        raise ValueError('La extensión atraviesa demasiadas teselas; reduce el polígono.')
    os.environ.setdefault('GDAL_DISABLE_READDIR_ON_OPEN', 'EMPTY_DIR')
    os.environ.setdefault('CPL_VSIL_CURL_ALLOWED_EXTENSIONS', '.tif')
    with rasterio.Env(GDAL_HTTP_MAX_RETRY='2', GDAL_HTTP_RETRY_DELAY='1'):
        with ExitStack() as stack:
            datasets = []
            for la, lo in tiles:
                url = _tile_url(la, lo)
                try:
                    datasets.append(stack.enter_context(rasterio.open(url)))
                except Exception as exc:
                    raise RuntimeError(f'No se pudo abrir tesela Copernicus {la},{lo}: {exc}') from exc
            out, tx = merge(datasets, bounds=bounds, res=(1/3600, 1/3600),
                            nodata=-32767, masked=False)
            if out.size > 8_000_000:
                raise ValueError('El recorte excede el límite de píxeles.')
            profile = datasets[0].profile.copy()
            profile.update(driver='GTiff', height=out.shape[1], width=out.shape[2],
                           count=1, transform=tx, crs='EPSG:4326',
                           dtype=out.dtype, nodata=-32767, compress='deflate')
            with MemoryFile() as mem:
                with mem.open(**profile) as dst:
                    dst.write(out[:1])
                return mem.read(), {'fuente': 'Copernicus DEM GLO-30 / AWS Open Data',
                                    'teselas': [_tile_url(a,b) for a,b in tiles],
                                    'contexto_km': context_km,
                                    'advertencia': 'Pendiente raster preliminar; verificar unidad de análisis MDSF.'}


def worldcover_resumen(polygon):
    """Obtiene proporciones de clases ESA WorldCover dentro del polígono.

    Requiere pystac-client y planetary-computer. No infiere permeabilidad ni
    convierte automáticamente clases WorldCover a categorías MDSF.
    """
    _validate_area(polygon)
    from pystac_client import Client
    import planetary_computer
    catalog = Client.open(STAC_URL)
    items = list(catalog.search(collections=['esa-worldcover'],
                                intersects=mapping(polygon), max_items=12).items())
    if not items:
        raise ValueError('No se encontraron escenas WorldCover para el polígono.')
    # Preferir la edición más reciente por celda; no sumar 2020 y 2021
    # sobre una misma ubicación, lo que duplicaría el conteo.
    by_cell = {}
    for item in items:
        key = item.id.rsplit('_', 1)[0] if '_' in item.id else item.id
        year = str(item.properties.get('datetime') or item.properties.get('start_datetime') or '')
        if key not in by_cell or year > by_cell[key][0]:
            by_cell[key] = (year, item)
    items = [pair[1] for pair in by_cell.values()]
    counts = Counter()
    year_set = set()
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', GDAL_HTTP_MAX_RETRY='2'):
        for item in items:
            if 'map' not in item.assets:
                continue
            href = planetary_computer.sign(item.assets['map'].href)
            with rasterio.open(href) as src:
                geom = transform_geom('EPSG:4326', src.crs, mapping(polygon))
                try:
                    arr, _ = mask(src, [geom], crop=True, filled=False, indexes=1)
                except ValueError:
                    continue
                valid = arr.compressed()
                counts.update(int(v) for v in valid if int(v) in WORLDCOVER_CLASSES)
                year_set.add(str(item.properties.get('datetime', 'sin fecha'))[:4])
    total = sum(counts.values())
    if not total:
        raise ValueError('No hay píxeles válidos WorldCover dentro del polígono.')
    return {
        'fuente': 'ESA WorldCover / Planetary Computer',
        'anios_catalogo': sorted(year_set),
        'total_pixeles': total,
        'clases': [{'codigo': k, 'clase': WORLDCOVER_CLASSES[k],
                    'pixeles': v, 'porcentaje': round(v*100/total, 2)}
                   for k,v in counts.most_common()],
        'advertencia': 'Cobertura satelital, no clase hidrológica MDSF ni permeabilidad. Validar conversión.'
    }
