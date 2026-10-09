"""Detección exploratoria de taludes, cauces y posibles abanicos aluviales.

No constituye cartografía oficial ni valida la presencia de abanicos aluviales.
El análisis usa un DEM con contexto aguas arriba y geometrías OSM opcionales.
"""
from __future__ import annotations
import io
import math
import numpy as np
import requests
import rasterio
from rasterio.io import MemoryFile
from rasterio.warp import reproject, calculate_default_transform, Resampling
from rasterio.features import shapes
from shapely.geometry import shape, LineString, mapping
from shapely.ops import transform as shp_transform, unary_union
from pyproj import Transformer
from scipy.ndimage import gaussian_filter, maximum_filter, minimum_filter, binary_dilation, label


def _metric_dem(data, polygon, max_pixels=5_000_000):
    with MemoryFile(data) as mem, mem.open() as src:
        if src.crs is None: raise ValueError('DEM sin CRS')
        lon, lat = polygon.centroid.x, polygon.centroid.y
        epsg = (32700 if lat < 0 else 32600) + int((lon+180)//6)+1
        crs = f'EPSG:{epsg}'
        transform, w, h = calculate_default_transform(src.crs, crs, src.width, src.height, *src.bounds)
        if w*h > max_pixels: raise ValueError('DEM demasiado grande para análisis interactivo')
        arr = np.full((h,w), -9999., dtype=np.float32)
        reproject(rasterio.band(src,1), arr, src_transform=src.transform, src_crs=src.crs,
                  src_nodata=src.nodata, dst_transform=transform, dst_crs=crs,
                  dst_nodata=-9999., resampling=Resampling.bilinear)
        return arr, transform, crs


def _lineas_osm(polygon, radio_m=2000, timeout=22):
    """OSM Overpass: cauces cartografiados, cobertura incompleta y no oficial."""
    lat, lon = polygon.centroid.y, polygon.centroid.x
    query = f'[out:json][timeout:18];(way["waterway"~"^(stream|river|canal|drain)$"](around:{int(radio_m)},{lat:.6f},{lon:.6f}););out geom;'
    for url in ('https://overpass.kumi.systems/api/interpreter','https://overpass-api.de/api/interpreter'):
        try:
            r=requests.post(url, data={'data':query}, timeout=timeout)
            r.raise_for_status()
            lines=[]
            for el in r.json().get('elements',[]):
                pts=[(p['lon'],p['lat']) for p in el.get('geometry',[])]
                if len(pts)>=2: lines.append(LineString(pts))
            return lines, None
        except Exception as e: last=str(e)
    return [], f'OSM no disponible: {last}'


def detectar(polygon, dem_bytes, consultar_osm=True, umbral_talud_grados=30.0):
    """Distancias mínimas desde el polígono (0 si intersecta), en metros.

    Cauce: OSM si disponible, más eje de drenaje topográfico aproximado.
    Abanico: SOLO candidato geomorfológico, sin asignación de clase MDSF.
    """
    z, tr, crs = _metric_dem(dem_bytes, polygon)
    valid=np.isfinite(z)&(z!=-9999)
    if valid.sum()<100: raise ValueError('DEM insuficiente para detección')
    # Relleno para derivadas: sólo en contexto raster válido; nunca interpretar huecos como terreno.
    z0=np.where(valid,z,np.nanmedian(z[valid]))
    smooth=gaussian_filter(z0, 1.2)
    dy,dx=abs(tr.e),abs(tr.a)
    gy,gx=np.gradient(smooth,dy,dx)
    slope=np.degrees(np.arctan(np.hypot(gx,gy)))
    local_relief=maximum_filter(smooth,size=9)-minimum_filter(smooth,size=9)
    # Agrupar sectores escarpados, evitar píxeles aislados.
    talud_mask=(slope>=umbral_talud_grados)&(local_relief>=8)&valid
    talud_mask=binary_dilation(talud_mask,iterations=1)&valid
    # Índice de convergencia de flujo topográfico (proxy, NO red hidrológica calibrada).
    # Curvatura planimétrica simplificada + concavidad topográfica multiescala.
    broad=gaussian_filter(z0, 8)
    concavity=broad-smooth
    drainage_mask=(concavity>max(1.5, 0.6*float(np.nanstd(concavity[valid]))))&(slope>2)&valid
    drainage_mask=binary_dilation(drainage_mask,iterations=1)&valid
    to_metric=Transformer.from_crs('EPSG:4326',crs,always_xy=True)
    p=shp_transform(to_metric.transform,polygon)
    def polygons_from_mask(mask):
        if not mask.any(): return []
        return [shape(g) for g,v in shapes(mask.astype('uint8'),mask=mask,transform=tr) if v==1]
    def distance(mask):
        polys=polygons_from_mask(mask)
        return round(float(p.distance(unary_union(polys))),1) if polys else None
    dtalud=distance(talud_mask)
    ddrain=distance(drainage_mask)
    osm_lines=[]; osm_error=None
    if consultar_osm:
        osm_lines,osm_error=_lineas_osm(polygon)
    osm_m=[shp_transform(to_metric.transform,g) for g in osm_lines]
    dosm=round(float(p.distance(unary_union(osm_m))),1) if osm_m else None
    # Indicador orientativo de depósitos de pie de ladera: relieve moderado/bajo,
    # convergencia cercana y fuerte pendiente próxima. No equivale a abanico cartografiado.
    pxmask=rasterio.features.geometry_mask([mapping(p)],out_shape=z.shape,transform=tr,invert=True)
    core=pxmask&valid
    near_steep=binary_dilation(talud_mask,iterations=max(1,int(300/max(dx,dy))))
    fan_proxy=core&(slope>=1)&(slope<=12)&near_steep&binary_dilation(drainage_mask,iterations=max(1,int(150/max(dx,dy))))
    pct=round(100*float(fan_proxy.sum())/max(1,int(core.sum())),1)
    # NO concluir 'fuera de cauce' cuando OSM falta, ni 'en abanico' por proxy.
    return {
      'distancia_talud_potencial_m':dtalud,
      'distancia_cauce_osm_m':dosm,
      'distancia_drenaje_topografico_proxy_m':ddrain,
      'candidato_abanico_porcentaje_poligono':pct,
      'candidato_abanico_detectado':bool(pct>=10),
      'cantidad_cauces_osm':len(osm_lines),
      'fuente_cauces':'OpenStreetMap / Overpass (cartografía colaborativa)',
      'fuente_terreno':'Copernicus DEM / análisis morfométrico exploratorio',
      'advertencias':[
        'Taludes detectados por pendiente y relieve local: requieren verificación.',
        'Drenaje topográfico es un proxy de convergencia, no cauce confirmado.',
        'Abanico aluvial: detección de CANDIDATOS; no se asigna automáticamente categoría del manual.',
        'La distancia a cauce no equivale a distancia a intervenciones del cauce.',
        'Un resultado nulo o ausencia de cauces OSM NO significa ausencia de amenaza.',
      ]+([osm_error] if osm_error else [])
    }
