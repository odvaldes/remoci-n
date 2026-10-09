"""Drenaje derivado del DEM (D8 priority-flood) y candidatos a abanicos.

Los cauces modelados son trayectorias de escorrentía, no cursos oficiales.
Los abanicos son CANDIDATOS geomorfológicos, no polígonos validados.
"""
from __future__ import annotations
import heapq
import math
from collections import deque

import numpy as np
from scipy.ndimage import gaussian_filter, maximum_filter, minimum_filter, binary_dilation, label
import rasterio
from rasterio.io import MemoryFile
from rasterio.warp import reproject, calculate_default_transform, Resampling
from rasterio.features import shapes, geometry_mask
from shapely.geometry import shape, mapping, LineString
from shapely.ops import transform as shp_transform, unary_union
from pyproj import Transformer

NEIGHBORS = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]


def _metric_dem(data, polygon, max_pixels=2_500_000):
    with MemoryFile(data) as mem, mem.open() as src:
        if src.crs is None:
            raise ValueError('DEM sin CRS')
        lon, lat = polygon.centroid.x, polygon.centroid.y
        epsg = (32700 if lat < 0 else 32600) + int((lon + 180) // 6) + 1
        crs = f'EPSG:{epsg}'
        tx, w, h = calculate_default_transform(src.crs, crs, src.width, src.height, *src.bounds)
        if w * h > max_pixels:
            raise ValueError('Área DEM demasiado grande; reduzca el polígono o resolución.')
        arr = np.full((h,w), -9999., dtype=np.float32)
        reproject(rasterio.band(src,1), arr, src_transform=src.transform, src_crs=src.crs,
                  src_nodata=src.nodata, dst_transform=tx, dst_crs=crs,
                  dst_nodata=-9999., resampling=Resampling.bilinear)
        return arr, tx, crs


def _priority_flow(z, valid):
    """Priority flood con trazado hacia celda previamente procesada.

    Las depresiones se conectan al borde del recorte; el caudal acumulado
    está truncado en el borde (no sustituye cuenca aguas arriba completa).
    """
    h, w = z.shape
    visited = np.zeros((h,w), dtype=bool)
    downstream = np.full(h*w, -1, dtype=np.int32)
    order = []
    heap = []
    for r in range(h):
        for c in (0,w-1):
            if valid[r,c] and not visited[r,c]:
                visited[r,c] = True
                heapq.heappush(heap,(float(z[r,c]),r*w+c))
    for c in range(w):
        for r in (0,h-1):
            if valid[r,c] and not visited[r,c]:
                visited[r,c] = True
                heapq.heappush(heap,(float(z[r,c]),r*w+c))
    # Las celdas vecinas a huecos nodata también actúan como borde.
    for r in range(1,h-1):
        for c in range(1,w-1):
            if valid[r,c] and not visited[r,c] and any(not valid[r+dr,c+dc] for dr,dc in NEIGHBORS):
                visited[r,c] = True
                heapq.heappush(heap,(float(z[r,c]),r*w+c))
    while heap:
        height, idx = heapq.heappop(heap)
        order.append(idx)
        r,c = divmod(idx,w)
        for dr,dc in NEIGHBORS:
            rr,cc = r+dr,c+dc
            if 0 <= rr < h and 0 <= cc < w and valid[rr,cc] and not visited[rr,cc]:
                visited[rr,cc] = True
                ni = rr*w+cc
                downstream[ni] = idx
                heapq.heappush(heap,(max(float(z[rr,cc]),height),ni))
    accum = np.zeros(h*w, dtype=np.float32)
    accum[valid.ravel()] = 1
    for idx in reversed(order):
        dst = downstream[idx]
        if dst >= 0:
            accum[dst] += accum[idx]
    return accum.reshape(h,w), downstream


def _polys(mask, tr, min_area_m2=0):
    result=[]
    for g,v in shapes(mask.astype('uint8'), mask=mask, transform=tr):
        if v==1:
            p=shape(g)
            if p.area>=min_area_m2:
                result.append(p)
    return result


def _dist(p, geoms):
    return round(float(p.distance(unary_union(geoms))),1) if geoms else None


def _geojson_geoms(geoms, metric_crs, limit=100):
    tx=Transformer.from_crs(metric_crs,'EPSG:4326',always_xy=True)
    return [mapping(shp_transform(tx.transform,g)) for g in geoms[:limit]]


def detectar(polygon, dem_bytes, umbral_talud_grados=30.0,
             area_min_cauce_ha=15.0, consultar_osm=False):
    """Detecta drenajes D8 y sectores de transición ladera-piedemonte.

    Umbral cauce en hectáreas de área contribuyente DEL RECORTE, por lo que
    puede subestimar cauces en cuencas mayores. Requiere DEM con contexto.
    """
    z,tr,crs = _metric_dem(dem_bytes,polygon)
    valid=np.isfinite(z)&(z!=-9999)
    if valid.sum()<100:
        raise ValueError('DEM insuficiente para análisis hidrológico')
    dx,dy=abs(tr.a),abs(tr.e)
    cell_area=dx*dy
    z0=np.where(valid,z,np.median(z[valid]))
    smooth=gaussian_filter(z0,1.0)
    gy,gx=np.gradient(smooth,dy,dx)
    slope=np.degrees(np.arctan(np.hypot(gx,gy)))
    relief=maximum_filter(smooth,size=11)-minimum_filter(smooth,size=11)
    talud=(slope>=umbral_talud_grados)&(relief>=8)&valid
    talud=binary_dilation(talud,iterations=1)&valid
    accum, downstream = _priority_flow(z0,valid)
    area_ha=accum*cell_area/10000
    channel=(area_ha>=area_min_cauce_ha)&valid
    # Eliminar celdas aisladas y cauces muy cortos para no confundir ruido.
    channel_labels,n=label(channel,np.ones((3,3),dtype=np.uint8))
    if n:
        counts=np.bincount(channel_labels.ravel())
        channel &= (counts[channel_labels]>=3)&(channel_labels>0)
    # Buscar puntos donde un drenaje concentrado sale de una ladera
    # relativamente empinada hacia un piedemonte de menor pendiente.
    h,w=z.shape
    outlets=[]
    min_cells=max(2,int(math.ceil(50/max(dx,dy))))
    for r,c in zip(*np.where(channel & (slope<=12) & (slope>=0.3))):
        idx=r*w+c
        # aguas arriba: encontrar por proximidad topográfica a un canal empinado
        r0=max(0,r-min_cells*2);r1=min(h,r+min_cells*2+1)
        c0=max(0,c-min_cells*2);c1=min(w,c+min_cells*2+1)
        upslope=(channel[r0:r1,c0:c1] & (slope[r0:r1,c0:c1]>=16))
        if not upslope.any():
            continue
        # relieve próximo y cambio de pendiente (no prueba depósito sedimentario)
        if float(np.max(z0[r0:r1,c0:c1])-np.min(z0[r0:r1,c0:c1]))<25:
            continue
        outlets.append((r,c,float(area_ha[r,c])))
    # Evitar múltiples candidatos en el mismo abanico
    outlets.sort(key=lambda t:t[2],reverse=True)
    selected=[]
    separation=max(3,int(250/max(dx,dy)))
    for r,c,a in outlets:
        if all((r-rr)**2+(c-cc)**2>separation**2 for rr,cc,_ in selected):
            selected.append((r,c,a))
        if len(selected)>=15:
            break
    # Zonas candidatas al pie de cada salida: relieve suave, distancia <=300m,
    # bajo el punto de salida o levemente por encima (incertidumbre DEM).
    yy,xx=np.ogrid[:h,:w]
    fan=np.zeros((h,w),dtype=bool)
    for r,c,a in selected:
        radius=max(2,int(300/max(dx,dy)))
        local=((yy-r)**2+(xx-c)**2<=radius**2)
        fan |= local&(slope<=12)&(slope>=0.2)&(z0<=z0[r,c]+4)&valid
    # No incluir canales enteros como abanicos
    fan &= ~talud
    # Para evitar polígonos fragmentados muy pequeños
    fan_polys=_polys(fan,tr,min_area_m2=max(1000,cell_area*8))
    talud_polys=_polys(talud,tr,min_area_m2=cell_area*2)
    # Cauces vectoriales simplificados desde píxeles de red, sin inventar trazas
    channel_polys=_polys(channel,tr,min_area_m2=cell_area*3)
    tx=Transformer.from_crs('EPSG:4326',crs,always_xy=True)
    p=shp_transform(tx.transform,polygon)
    core=geometry_mask([mapping(p)],out_shape=z.shape,transform=tr,invert=True)&valid
    fan_pct=round(100*float((fan&core).sum())/max(1,int(core.sum())),1)
    # Detección geomorfológica basada en topografía, no red OSM.
    return {
      'distancia_talud_potencial_m':_dist(p,talud_polys),
      'distancia_cauce_modelado_m':_dist(p,channel_polys),
      'distancia_cauce_osm_m':None,
      'distancia_drenaje_topografico_proxy_m':_dist(p,channel_polys),
      'candidato_abanico_porcentaje_poligono':fan_pct,
      'candidato_abanico_detectado':bool(fan_pct>=5),
      'cantidad_cauces_modelados':len(channel_polys),
      'cantidad_salidas_piedemonte_candidatas':len(selected),
      'cantidad_cauces_osm':0,
      'area_min_cauce_ha':area_min_cauce_ha,
      'fuente_cauces':'Drenaje D8 derivado del DEM; NO cauce oficial',
      'fuente_terreno':'Copernicus DEM / acumulación de flujo y morfometría',
      'capas_geojson':{
         'cauces_modelados':_geojson_geoms(channel_polys,crs,limit=150),
         'taludes':_geojson_geoms(talud_polys,crs,limit=150),
         'abanicos_candidatos':_geojson_geoms(fan_polys,crs,limit=75),
         'salidas_piedemonte':_geojson_geoms([shape({'type':'Point','coordinates':(tr.c+(c+.5)*tr.a,tr.f+(r+.5)*tr.e)}) for r,c,_ in selected],crs),
      },
      'advertencias':[
        'Los cauces son MODELADOS mediante acumulación de flujo; el DEM debe incluir la cuenca aportante.',
        'Los abanicos son CANDIDATOS topográficos; no se confirma deposición ni extensión del abanico.',
        'Un DEM de 30 m puede omitir quebradas pequeñas y conos aluviales estrechos.',
        'Los taludes identificados por pendiente requieren verificación.',
        'La distancia a cauces no equivale a distancia a intervenciones del cauce.',
        'Ausencia de detección NO significa ausencia de amenaza.',
      ],
    }
