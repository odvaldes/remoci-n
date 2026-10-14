"""GeoRiskAI Sentinel — módulo experimental de remoción en masa por flujos.

Este prototipo aplica escalas de amenaza MDSF 2025 y vulnerabilidad propia
del modelo tsunami. La agregación final es EXPLORATORIA, no IRD oficial.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import folium
import numpy as np
import pandas as pd
import requests
import streamlit as st
from folium.plugins import Draw
from pyproj import CRS, Transformer
from rasterio.io import MemoryFile
from rasterio.mask import mask
from rasterio.warp import calculate_default_transform, reproject, Resampling
from shapely.geometry import shape, mapping
from shapely.ops import transform as shapely_transform
from streamlit_folium import st_folium
from modelo_ird import (ESCALAS, TABLA_ESCORRENTIA, MATERIALIDAD, NORMATIVA,
    puntaje_pendiente, puntaje_escorrentia, coeficiente_escorrentia, calcular_factores,
    vulnerabilidad_tsunami, indice_exploratorio)

PRC_LASERENA_KMZ = (
    "https://mapas.laserena.cl/mapas/riesgos%20_NoEdificables/data/"
    "Mapa_Riesgos_y_Fajas_No_Edificables_PRC_2020.kmz"
)
PRC_COQUIMBO_ARCGIS = (
    "https://services6.arcgis.com/wCQahTSdHSiz4pOz/ArcGIS/rest/services/"
    "Planificador_Territorial_Coquimbo_WFL1/FeatureServer/4"
)
SERNAGEOMIN_WEBMAP_ID = "bd82ae84d40643019878dea882335381"
SERNAGEOMIN_EVENTS_LAYER = (
    "https://services3.arcgis.com/uZrwedu11XCCdHk1/arcgis/rest/services/"
    "M5T7___Mapa___Remociones_en_Masa__Chile_1962_2021__WFL1/FeatureServer/0"
)
KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}


def _coordinates(text):
    points = []
    for item in (text or "").strip().split():
        values = item.split(",")
        if len(values) >= 2:
            points.append([float(values[0]), float(values[1])])
    return points


def _kml_placemark_geometry(placemark):
    polygons = []
    for poly in placemark.findall(".//kml:Polygon", KML_NS):
        outer_node = poly.find("kml:outerBoundaryIs/kml:LinearRing/kml:coordinates", KML_NS)
        if outer_node is None:
            continue
        rings = [_coordinates(outer_node.text)]
        for inner in poly.findall("kml:innerBoundaryIs/kml:LinearRing/kml:coordinates", KML_NS):
            ring = _coordinates(inner.text)
            if ring:
                rings.append(ring)
        if rings[0]:
            polygons.append(rings)
    if len(polygons) == 1:
        return {"type": "Polygon", "coordinates": polygons[0]}
    if polygons:
        return {"type": "MultiPolygon", "coordinates": polygons}
    line = placemark.find(".//kml:LineString/kml:coordinates", KML_NS)
    if line is not None:
        coords = _coordinates(line.text)
        if len(coords) >= 2:
            return {"type": "LineString", "coordinates": coords}
    point = placemark.find(".//kml:Point/kml:coordinates", KML_NS)
    if point is not None:
        coords = _coordinates(point.text)
        if coords:
            return {"type": "Point", "coordinates": coords[0]}
    return None


def parse_kmz(content):
    """Convert a KMZ's KML placemarks to GeoJSON without GDAL/Fiona."""
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        kml_name = next((n for n in archive.namelist() if n.lower().endswith(".kml")), None)
        if not kml_name:
            raise ValueError("El KMZ no contiene un archivo KML.")
        root = ET.fromstring(archive.read(kml_name))
    features = []
    for placemark in root.findall(".//kml:Placemark", KML_NS):
        geom = _kml_placemark_geometry(placemark)
        if not geom:
            continue
        name = placemark.findtext("kml:name", default="", namespaces=KML_NS)
        description = placemark.findtext("kml:description", default="", namespaces=KML_NS)
        features.append({"type": "Feature", "properties": {"nombre": name, "detalle": description}, "geometry": geom})
    if not features:
        raise ValueError("No se encontraron geometrías compatibles en el KMZ.")
    return {"type": "FeatureCollection", "features": features}


@st.cache_data(ttl=86400, show_spinner=False)
def load_remote_kmz(url):
    response = requests.get(url, timeout=25)
    response.raise_for_status()
    return parse_kmz(response.content)


@st.cache_data(ttl=86400, show_spinner=False)
def load_arcgis_geojson(layer_url, bbox):
    """Fetch features intersecting [west, south, east, north] in EPSG:4326."""
    response = requests.get(
        layer_url.rstrip("/") + "/query",
        params={
            "where": "1=1", "outFields": "*", "returnGeometry": "true",
            "outSR": "4326", "f": "geojson", "resultRecordCount": 1500,
            "geometry": ",".join(str(v) for v in bbox),
            "geometryType": "esriGeometryEnvelope", "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("error"):
        raise RuntimeError(data["error"].get("message", "Error de ArcGIS"))
    return data


@st.cache_data(ttl=86400, show_spinner=False)
def load_sernageomin_hazard_layers(bbox):
    """Read the public SERNAGEOMIN ArcGIS web map and fetch visible feature layers."""
    item_url = f"https://www.arcgis.com/sharing/rest/content/items/{SERNAGEOMIN_WEBMAP_ID}/data"
    response = requests.get(item_url, params={"f": "json"}, timeout=25)
    response.raise_for_status()
    webmap = response.json()
    layers = []
    errors = []
    for item in webmap.get("operationalLayers", []):
        url = item.get("url", "")
        if not url or "FeatureServer" not in url:
            continue
        try:
            data = load_arcgis_geojson(url, bbox)
            if data.get("features"):
                layers.append({"name": item.get("title") or item.get("name") or "Capa SERNAGEOMIN", "data": data})
        except Exception as exc:
            errors.append(str(exc))
    if not layers and errors:
        raise RuntimeError("No se pudo consultar ninguna capa vectorial: " + "; ".join(errors[:2]))
    return layers


def count_layer_intersections(polygon, geojson):
    count = 0
    for feature in (geojson or {}).get("features", []):
        geometry = feature.get("geometry")
        if not geometry:
            continue
        try:
            if polygon.intersects(shape(geometry)):
                count += 1
        except Exception:
            continue
    return count

st.set_page_config(page_title="GeoRiskAI | Remoción en masa", page_icon="⛰️", layout="wide")
st.title("⛰️ GeoRiskAI Sentinel | Remoción en masa por flujos")
st.caption("Prototipo geoespacial nacional · Evaluación preliminar, no resultado IRD oficial")
st.warning("Este prototipo aplica las escalas de amenaza MDSF y reutiliza la vulnerabilidad del modelo tsunami. La agregación final no es oficial; las variables geotécnicas y geomorfológicas deben verificarse.")

@st.cache_data(show_spinner=False)
def load_dem_bytes(path: str):
    with open(path, "rb") as f:
        return f.read()


def normalize_polygon(geom):
    g = shape(geom) if isinstance(geom, dict) else geom
    if g.geom_type not in ("Polygon", "MultiPolygon"):
        raise ValueError("La geometría debe ser Polygon o MultiPolygon.")
    if not g.is_valid:
        g = g.buffer(0)
    if g.is_empty or not g.is_valid:
        raise ValueError("El polígono es inválido y no pudo corregirse.")
    if not (-76 <= g.centroid.x <= -66 and -57 <= g.centroid.y <= -17):
        st.info("El polígono parece estar fuera del territorio continental chileno. Comprueba que sus coordenadas estén en EPSG:4326.")
    return g


def uploaded_geojson(file):
    obj = json.load(file)
    if obj.get("type") == "FeatureCollection":
        if len(obj.get("features", [])) != 1:
            raise ValueError("El GeoJSON debe contener exactamente un polígono por evaluación.")
        geom = obj["features"][0]["geometry"]
    elif obj.get("type") == "Feature":
        geom = obj["geometry"]
    else:
        geom = obj
    return normalize_polygon(geom)


def geometry_area_ha(g):
    # UTM local, adecuado para estimar superficie del polígono
    lon, lat = g.centroid.x, g.centroid.y
    zone = int((lon + 180) // 6) + 1
    epsg = 32700 + zone if lat < 0 else 32600 + zone
    tx = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    gp = shapely_transform(tx.transform, g)
    return gp.area / 10000


def analyze_dem(dem_bytes, polygon):
    """Recorta DEM y calcula pendientes en grados, sobre grilla métrica reproyectada.

    El máximo de pendiente depende de resolución, calidad y ruido del DEM.
    Se reportan también mediana y p95 para control de calidad.
    """
    with MemoryFile(dem_bytes) as mem:
        with mem.open() as src:
            if src.crs is None:
                raise ValueError("El DEM debe tener un sistema de referencia definido.")
            trans = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
            projected_polygon = shapely_transform(trans.transform, polygon)
            cropped, cropped_transform = mask(src, [mapping(projected_polygon)], crop=True, filled=False)
            arr = cropped[0].astype("float32").filled(np.nan)
            if np.count_nonzero(np.isfinite(arr)) < 9:
                raise ValueError("El DEM no contiene suficientes píxeles válidos dentro del polígono.")
            lon, lat = polygon.centroid.x, polygon.centroid.y
            zone = int((lon + 180) // 6) + 1
            target_crs = CRS.from_epsg((32700 if lat < 0 else 32600) + zone)
            # La reproyección se realiza sobre el recorte, nunca sobre un raster nacional completo.
            from rasterio.transform import array_bounds
            h, w = arr.shape
            bounds = array_bounds(h, w, cropped_transform)
            dst_transform, dw, dh = calculate_default_transform(src.crs, target_crs, w, h, *bounds)
            if dw * dh > 10_000_000:
                raise ValueError("El área es demasiado grande para esta evaluación interactiva. Divide el polígono.")
            dst = np.full((dh, dw), np.nan, dtype="float32")
            reproject(source=arr, destination=dst, src_transform=cropped_transform,
                      src_crs=src.crs, dst_transform=dst_transform, dst_crs=target_crs,
                      src_nodata=np.nan, dst_nodata=np.nan, resampling=Resampling.bilinear)
            dy, dx = abs(dst_transform.e), abs(dst_transform.a)
            if min(dst.shape) < 3 or dx <= 0 or dy <= 0:
                raise ValueError("Recorte demasiado pequeño para calcular pendiente.")
            gy, gx = np.gradient(dst, dy, dx)
            slope = np.degrees(np.arctan(np.hypot(gx, gy)))
            # Excluir bordes del raster recortado para evitar pendientes espurias por nodata.
            slope[0, :] = np.nan; slope[-1, :] = np.nan
            slope[:, 0] = np.nan; slope[:, -1] = np.nan
            finite = slope[np.isfinite(slope)]
            elev = dst[np.isfinite(dst)]
            if finite.size == 0:
                raise ValueError("No se obtuvieron pendientes válidas.")
            return {
                "pendiente_max_grados": round(float(np.max(finite)), 2),
                "pendiente_p95_grados": round(float(np.percentile(finite, 95)), 2),
                "pendiente_mediana_grados": round(float(np.median(finite)), 2),
                "elevacion_min_m": round(float(np.min(elev)), 1),
                "elevacion_max_m": round(float(np.max(elev)), 1),
                "resolucion_m_aprox": round(float(max(dx, dy)), 1),
                "pixeles_pendiente_validos": int(finite.size),
            }

with st.sidebar:
    st.header("Área de estudio")
    pilot_comuna = st.selectbox("Comuna del piloto", ["La Serena", "Coquimbo", "La Serena y Coquimbo"])
    st.markdown("Dibuja **un polígono** en el mapa o sube un archivo GeoJSON en coordenadas WGS84 (EPSG:4326).")
    upload = st.file_uploader("Cargar polígono GeoJSON", type=["geojson", "json"])
    st.header("Capas de riesgo para el mapa")
    show_prc = st.checkbox("Mostrar zonas de riesgo del PRC", value=True)
    show_sernageomin = st.checkbox("Mostrar mapas/capas SERNAGEOMIN", value=True)
    show_sngm_events = st.checkbox("Mostrar catastro histórico SERNAGEOMIN (1962–2021)", value=True)
    st.header("Datos de elevación")
    st.caption("Opción A: cargar un DEM GeoTIFF que cubra el polígono. Opción B: configurar DEM_PATH en Streamlit Secrets o variable de entorno con ruta a un GeoTIFF accesible en el servidor.")
    dem_upload = st.file_uploader("DEM GeoTIFF (opcional)", type=["tif", "tiff"])
    st.caption("No se descarga automáticamente cartografía satelital. Esta versión calcula pendiente cuando se proporciona un DEM.")

COMMUNE_MAP_CONFIG = {
    "La Serena": {"center": [-29.90, -71.25], "zoom": 10, "bbox": [-71.42, -30.15, -71.02, -29.65]},
    "Coquimbo": {"center": [-29.97, -71.34], "zoom": 10, "bbox": [-71.56, -30.42, -71.10, -29.72]},
    "La Serena y Coquimbo": {"center": [-29.94, -71.30], "zoom": 9, "bbox": [-71.56, -30.42, -71.02, -29.65]},
}
map_config = COMMUNE_MAP_CONFIG[pilot_comuna]
m = folium.Map(location=map_config["center"], zoom_start=map_config["zoom"], tiles="CartoDB positron", control_scale=True)
folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(m)

prc_data = None
prc_geojson_layers = []
sernageomin_layers = []
sernageomin_events = None
source_messages = []
if show_prc:
    if pilot_comuna in {"La Serena", "La Serena y Coquimbo"}:
        try:
            prc_data = load_remote_kmz(PRC_LASERENA_KMZ)
            prc_geojson_layers.append({"name": "PRC La Serena 2020", "data": prc_data})
            folium.GeoJson(
                prc_data, name="PRC La Serena 2020 · zonas de riesgo/fajas",
                style_function=lambda _f: {"color": "#b51f2a", "weight": 1.5, "fillColor": "#e34a4a", "fillOpacity": 0.22},
                tooltip=folium.GeoJsonTooltip(fields=["nombre"], aliases=["Zona PRC"]),
            ).add_to(m)
        except Exception as exc:
            source_messages.append(f"No se pudo cargar el KMZ oficial de La Serena: {exc}")
    if pilot_comuna in {"Coquimbo", "La Serena y Coquimbo"}:
        try:
            coq_prc = load_arcgis_geojson(PRC_COQUIMBO_ARCGIS, map_config["bbox"])
            if coq_prc.get("features"):
                prc_geojson_layers.append({"name": "PRC Coquimbo (capa vectorial)", "data": coq_prc})
                folium.GeoJson(
                    coq_prc, name="PRC Coquimbo · áreas de riesgo (capa vectorial)",
                    style_function=lambda _f: {"color": "#b51f2a", "weight": 1.5, "fillColor": "#e34a4a", "fillOpacity": 0.22},
                    tooltip=folium.GeoJsonTooltip(fields=["ZONA", "LOCALIDAD", "NOMBRE"], aliases=["Zona", "Localidad", "Descripción"], labels=True),
                ).add_to(m)
                prc_data = coq_prc
        except Exception as exc:
            source_messages.append(f"No se pudo consultar la capa vectorial PRC Coquimbo: {exc}")

if show_sernageomin:
    try:
        sernageomin_layers = load_sernageomin_hazard_layers(map_config["bbox"])
        for idx, layer in enumerate(sernageomin_layers):
            folium.GeoJson(
                layer["data"], name=f"SERNAGEOMIN · {layer['name']}",
                style_function=lambda _f: {"color": "#6a3d9a", "weight": 1.1, "fillColor": "#8e63b6", "fillOpacity": 0.24},
                marker=folium.CircleMarker(radius=4, color="#6a3d9a", fill=True, fill_opacity=0.8),
            ).add_to(m)
    except Exception as exc:
        source_messages.append(f"No se pudieron consultar las capas de susceptibilidad SERNAGEOMIN: {exc}")

if show_sngm_events:
    try:
        sernageomin_events = load_arcgis_geojson(SERNAGEOMIN_EVENTS_LAYER, map_config["bbox"])
        if sernageomin_events.get("features"):
            folium.GeoJson(
                sernageomin_events, name="SERNAGEOMIN · eventos históricos 1962–2021",
                style_function=lambda _f: {"color": "#333333", "weight": 2, "fillColor": "#333333", "fillOpacity": 0.45},
                marker=folium.CircleMarker(radius=4, color="#292929", fill=True, fill_color="#f2a900", fill_opacity=0.95),
            ).add_to(m)
    except Exception as exc:
        source_messages.append(f"No se pudo consultar el catastro histórico de SERNAGEOMIN: {exc}")

Draw(export=False, draw_options={"polyline": False, "rectangle": True, "circle": False,
    "circlemarker": False, "marker": False}, edit_options={"edit": True, "remove": True}).add_to(m)
folium.LayerControl().add_to(m)
map_data = st_folium(m, width=None, height=540, returned_objects=["all_drawings", "last_active_drawing"], key="mapa_remocion")

st.caption("Fuentes separadas en el mapa: PRC = regulación/áreas de riesgo del instrumento; SERNAGEOMIN = susceptibilidad/peligro geológico; catastro = eventos observados, no una zona de peligro.")
for message in source_messages:
    st.warning(message)
if pilot_comuna in {"Coquimbo", "La Serena y Coquimbo"} and show_prc:
    st.info("El PRC actualizado de Coquimbo está vigente desde el 5 de enero de 2026. La capa vectorial consultada no expone claramente en sus metadatos la versión del instrumento; confirma el polígono con el PRC vigente antes de usarlo para decisiones normativas.")
st.markdown(
    "Fuentes: [PRC La Serena 2020 (visor municipal)](https://mapas.laserena.cl/mapas/riesgos%20_NoEdificables/) · "
    "[PRC Coquimbo vigente y documentos](https://www.bcn.cl/leychile/Navegar?idNorma=1219776) · "
    "[Mapa SERNAGEOMIN de susceptibilidad de flujos](https://www.arcgis.com/apps/mapviewer/index.html?webmap=bd82ae84d40643019878dea882335381) · "
    "[SERNAGEOMIN Coquimbo Norte, IR-18-68](https://catalogobiblioteca.sernageomin.cl/Archivos/15633%20-texto%20y%20mapa-red.pdf) · "
    "[SERNAGEOMIN Coquimbo Sur, IR-21-88](https://portalgeo.sernageomin.cl/Informes_PDF_Nac/RM-2021-01.pdf) · "
    "[Catastro histórico SERNAGEOMIN](https://services3.arcgis.com/uZrwedu11XCCdHk1/arcgis/rest/services/M5T7___Mapa___Remociones_en_Masa__Chile_1962_2021__WFL1/FeatureServer)"
)

polygon = None
try:
    if upload is not None:
        polygon = uploaded_geojson(upload)
    elif map_data and map_data.get("all_drawings"):
        drawings = map_data["all_drawings"]
        if len(drawings) > 1:
            st.info("Hay varios polígonos dibujados; se analizará el último. Para otra evaluación elimina los anteriores.")
        polygon = normalize_polygon(drawings[-1]["geometry"])
except Exception as exc:
    st.error(f"Error de geometría: {exc}")

if polygon is None:
    st.info("Selecciona el polígono para activar el análisis.")
    st.stop()

area = geometry_area_ha(polygon)
st.subheader("Caracterización del polígono")
c1, c2, c3 = st.columns(3)
c1.metric("Superficie", f"{area:,.2f} ha")
c2.metric("Longitud centroide", f"{polygon.centroid.x:.5f}°")
c3.metric("Latitud centroide", f"{polygon.centroid.y:.5f}°")

st.subheader("Cruce con cartografía de referencia")
prc_hits = sum(count_layer_intersections(polygon, layer["data"]) for layer in prc_geojson_layers)
sngm_hazard_hits = sum(count_layer_intersections(polygon, layer["data"]) for layer in sernageomin_layers)
sngm_event_hits = count_layer_intersections(polygon, sernageomin_events)
hits = st.columns(3)
hits[0].metric("Elementos PRC intersectados", prc_hits if prc_geojson_layers else "Sin capa")
hits[1].metric("Polígonos SERNAGEOMIN intersectados", sngm_hazard_hits if sernageomin_layers else "Sin capa")
hits[2].metric("Eventos históricos intersectados", sngm_event_hits if sernageomin_events else "Sin capa")
st.caption("El cruce indica intersección geométrica con las capas cargadas; no determina por sí solo exposición, nivel de riesgo, permiso de edificación ni peligro actual.")

result = {"superficie_ha": round(area, 4), "fuente": "polígono suministrado por el usuario"}
dem_bytes = None
if dem_upload is not None:
    dem_bytes = dem_upload.getvalue()
else:
    dem_path = os.environ.get("DEM_PATH", "")
    try:
        dem_path = st.secrets.get("DEM_PATH", dem_path)
    except Exception:
        pass
    if dem_path and os.path.isfile(dem_path):
        dem_bytes = load_dem_bytes(dem_path)

if dem_bytes is not None:
    try:
        with st.spinner("Procesando relieve y pendientes..."):
            result.update(analyze_dem(dem_bytes, polygon))
        st.success("Pendientes calculadas sobre el DEM proporcionado.")
        cols = st.columns(4)
        cols[0].metric("Pendiente máxima", f"{result['pendiente_max_grados']}°")
        cols[1].metric("Pendiente p95", f"{result['pendiente_p95_grados']}°")
        cols[2].metric("Elevación mínima", f"{result['elevacion_min_m']} m")
        cols[3].metric("Elevación máxima", f"{result['elevacion_max_m']} m")
        st.caption("Pendiente máxima derivada del DEM: resultado preliminar sensible a resolución, errores y delimitación. Verificar la celda de análisis exigida por el manual MDSF.")
    except Exception as exc:
        st.error(f"No se pudo procesar el DEM: {exc}")
else:
    st.info("Para calcular pendientes, sube un DEM GeoTIFF que cubra el polígono. El visor nacional funciona sin DEM, pero no inventa valores de pendiente.")

st.subheader("Evaluación de amenaza por flujos — escalas MDSF 2025")
st.caption("Se aplican los pesos INTERNOS de condicionantes de generación y área de alcance del manual. La combinación de ambos factores no está definida en este manual de escalas.")
with st.expander("Cómo se determina la escorrentía (tabla 1, página 10)", expanded=True):
    ca, cb = st.columns(2)
    cobertura = ca.selectbox("Cobertura de suelo", list(TABLA_ESCORRENTIA))
    tipo_suelo = cb.selectbox("Permeabilidad del suelo", list(TABLA_ESCORRENTIA[cobertura]))
    slope_pct = None
    if "pendiente_max_grados" in result:
        slope_pct = float(np.tan(np.radians(result["pendiente_max_grados"])) * 100)
        st.caption(f"Pendiente máxima del DEM: {result['pendiente_max_grados']}° ({slope_pct:.1f}%). Revisar representatividad de la celda de análisis.")
    slope_manual = st.number_input("Pendiente (%) para tabla de escorrentía", min_value=0.0,
                                   value=round(slope_pct, 2) if slope_pct is not None else 0.0, step=0.5)
    if slope_pct is None:
        st.info("Sin DEM: ingresa la pendiente medida. No se presupone que el polígono tenga pendiente 0%.")
    coef = coeficiente_escorrentia(cobertura, tipo_suelo, slope_manual)
    st.metric("Coeficiente según tabla MDSF", f"{coef:.2f}")

usar_pendiente_dem = "pendiente_max_grados" in result
pendiente_sel = None
if usar_pendiente_dem:
    auto_pend = puntaje_pendiente(result["pendiente_max_grados"])
    st.write(f"Pendiente desde DEM: **{result['pendiente_max_grados']}°**; valoración automática: **{auto_pend if auto_pend is not None else 'no definida para ≤1°'}**")
    usar_auto = st.checkbox("Usar pendiente del DEM como valoración preliminar", value=auto_pend is not None, disabled=auto_pend is None)
    if usar_auto:
        pendiente_sel = auto_pend

selecciones = {}
for factor in ESCALAS:
    if factor == "pendiente" and pendiente_sel is not None:
        selecciones[factor] = pendiente_sel
        continue
    if factor == "escorrentia":
        usar_tabla = st.checkbox("Usar coeficiente de escorrentía de la tabla MDSF", value=True)
        if usar_tabla:
            selecciones[factor] = puntaje_escorrentia(coef)
            continue
    etiqueta = {"pendiente": "Pendiente de ladera", "escorrentia": "Coeficiente de escorrentía",
                "fundacion": "Suelo de fundación (antecedente geotécnico)",
                "localizacion": "Localización respecto a cauce / abanico aluvial",
                "taludes": "Distancia a taludes", "intervencion": "Distancia a intervención del cauce"}[factor]
    opciones = ["Sin información"] + list(ESCALAS[factor])
    seleccionado = st.selectbox(etiqueta, opciones, key=f"rm_{factor}")
    selecciones[factor] = ESCALAS[factor].get(seleccionado) if seleccionado != "Sin información" else None

factores = calcular_factores(selecciones)
if factores["completo"]:
    cgen, calc = st.columns(2)
    cgen.metric("Condicionantes de generación", f"{factores['condicionantes_generacion']:.1%}")
    calc.metric("Área de alcance", f"{factores['area_alcance']:.1%}")
else:
    st.info("Amenaza incompleta. Faltan: " + ", ".join(factores["faltantes"]))

st.subheader("Vulnerabilidad — valoración propia del modelo tsunami")
st.caption("Se reutiliza la vulnerabilidad de GeoRiskAI Sentinel: materialidad (75%) y antigüedad normativa (25%). NO es la vulnerabilidad oficial del manual de remoción en masa.")
v1, v2 = st.columns(2)
material = v1.selectbox("Vulnerabilidad por materialidad", list(MATERIALIDAD))
norma = v2.selectbox("Antigüedad normativa", list(NORMATIVA))
vuln = vulnerabilidad_tsunami(material, norma)
st.metric("Vulnerabilidad del proyecto", f"{vuln:.1%}")

st.subheader("Integración de amenaza y vulnerabilidad — ponderaciones del proyecto")
st.warning("El manual de escalas proporcionado no contiene la fórmula que combina condicionantes y alcance, ni una fórmula para combinar esta amenaza con tu vulnerabilidad tsunami. La ponderación 66,7% amenaza y 33,3% vulnerabilidad corresponde a GeoRiskAI Sentinel, no al manual MDSF. La agregación interna entre condicionantes y alcance continúa siendo una hipótesis configurable.")
p_gen = st.slider("Peso de condicionantes de generación dentro de amenaza (%) — provisional", 0, 100, 50, 5) / 100
p_amenaza = 0.667
st.info("Ponderación fija del modelo: Amenaza 66,7% · Vulnerabilidad 33,3%")
st.caption(f"Área de alcance: {1-p_gen:.0%} de la amenaza. Vulnerabilidad: {1-p_amenaza:.0%} del índice combinado.")
resultado_indice = None
if factores["completo"]:
    resultado_indice = indice_exploratorio(factores["condicionantes_generacion"],
        factores["area_alcance"], vuln, p_gen, p_amenaza)
    c_a, c_b = st.columns(2)
    c_a.metric("Amenaza combinada (exploratoria)", f"{resultado_indice['amenaza_exploratoria']:.1%}")
    c_b.metric("Índice combinado (NO oficial)", f"{resultado_indice['indice_exploratorio']:.1%}")
else:
    st.error("Índice combinado: no calculado. Completa los seis subfactores de amenaza.")

report = {
    "aplicacion": "GeoRiskAI Sentinel - Remoción en masa por flujos",
    "fecha_utc": datetime.now(timezone.utc).isoformat(),
    "estado_ird": "NO OFICIAL — escenario exploratorio" if resultado_indice else "NO CALCULADO",
    "advertencia": "Escalas de amenaza MDSF 2025; vulnerabilidad del modelo tsunami; integración de pesos no validada como MDSF.",
    "geometria_epsg4326": mapping(polygon), "caracterizacion_terreno": result,
    "escalas_amenaza": selecciones, "factores_amenaza": factores,
    "vulnerabilidad": {"materialidad": material, "normativa": norma, "puntaje": vuln},
    "pesos_modelo": {"condicionantes_generacion": p_gen, "area_alcance": 1-p_gen,
                              "amenaza": p_amenaza, "vulnerabilidad": 1-p_amenaza},
    "resultado_exploratorio": resultado_indice,
}
st.download_button("Descargar ficha JSON", data=json.dumps(report, ensure_ascii=False, indent=2),
                   file_name="georiskai_remocion_resultado.json", mime="application/json")
st.download_button("Descargar polígono GeoJSON", data=json.dumps({"type": "Feature", "properties": {}, "geometry": mapping(polygon)}, ensure_ascii=False),
                   file_name="poligono_estudio.geojson", mime="application/geo+json")
