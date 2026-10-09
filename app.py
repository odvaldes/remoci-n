"""GeoRiskAI Sentinel — módulo experimental de remoción en masa por flujos.

Este prototipo aplica escalas de amenaza MDSF 2025 y vulnerabilidad propia
del modelo tsunami. La agregación final es EXPLORATORIA, no IRD oficial.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from datetime import datetime, timezone

import folium
import numpy as np
import pandas as pd
import streamlit as st
from folium.plugins import Draw
from pyproj import CRS, Transformer
from rasterio.io import MemoryFile
from rasterio.mask import mask
from rasterio.warp import calculate_default_transform, reproject, Resampling
from shapely.geometry import shape, mapping
from shapely.ops import transform as shapely_transform
from streamlit_folium import st_folium
from fuentes_geo import copernicus_dem_bytes, worldcover_resumen
from modelo_ird import (ESCALAS, TABLA_ESCORRENTIA, MATERIALIDAD, NORMATIVA,
    puntaje_pendiente, puntaje_escorrentia, coeficiente_escorrentia, calcular_factores,
    vulnerabilidad_tsunami, indice_exploratorio)

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
    st.markdown("Dibuja **un polígono** en el mapa o sube un archivo GeoJSON en coordenadas WGS84 (EPSG:4326).")
    upload = st.file_uploader("Cargar polígono GeoJSON", type=["geojson", "json"])
    st.header("Datos de elevación")
    st.caption("Opción A: cargar un DEM GeoTIFF que cubra el polígono. Opción B: configurar DEM_PATH en Streamlit Secrets o variable de entorno con ruta a un GeoTIFF accesible en el servidor.")
    dem_upload = st.file_uploader("DEM GeoTIFF (opcional)", type=["tif", "tiff"])
    st.header("Fuentes geoespaciales automáticas")
    usar_copernicus = st.checkbox("Consultar Copernicus DEM GLO-30 automáticamente", value=True)
    usar_worldcover = st.checkbox("Consultar ESA WorldCover automáticamente", value=True)
    st.caption("Se requiere conexión del servidor a Internet. Consultas remotas limitadas a polígonos pequeños; no se descarga Chile completo.")

m = folium.Map(location=[-33.45, -70.65], zoom_start=5, tiles="CartoDB positron", control_scale=True)
folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(m)
Draw(export=False, draw_options={"polyline": False, "rectangle": True, "circle": False,
    "circlemarker": False, "marker": False}, edit_options={"edit": True, "remove": True}).add_to(m)
folium.LayerControl().add_to(m)
map_data = st_folium(m, width=None, height=540, returned_objects=["all_drawings", "last_active_drawing"], key="mapa_remocion")

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

fuentes_automaticas = {}
if dem_bytes is None and usar_copernicus:
    try:
        with st.spinner("Consultando Copernicus DEM GLO-30 en la nube..."):
            dem_bytes, metadata_dem = copernicus_dem_bytes(polygon)
            fuentes_automaticas["dem"] = metadata_dem
        st.success("DEM obtenido automáticamente desde Copernicus.")
    except Exception as exc:
        st.warning(f"Consulta automática DEM no disponible: {exc}. Puedes cargar un GeoTIFF manualmente.")

if usar_worldcover:
    try:
        with st.spinner("Consultando ESA WorldCover..."):
            resumen_cobertura = worldcover_resumen(polygon)
            fuentes_automaticas["worldcover"] = resumen_cobertura
        st.subheader("Cobertura de suelo — ESA WorldCover")
        st.dataframe(pd.DataFrame(resumen_cobertura["clases"]), use_container_width=True, hide_index=True)
        st.caption("La cobertura se presenta como antecedente; no se asigna automáticamente la permeabilidad ni el coeficiente de escorrentía MDSF.")
    except Exception as exc:
        st.warning(f"WorldCover no disponible para esta consulta: {exc}. Continúa con clasificación manual.")

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
    st.info("No se obtuvo un DEM. Intenta nuevamente la consulta automática o sube un GeoTIFF. No se inventan pendientes.")

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
    "fuentes_automaticas": fuentes_automaticas,
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
