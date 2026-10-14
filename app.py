"""GeoRiskAI Relaves — prototipo de monitoreo y exposición (no evaluación ingenieril)."""
from __future__ import annotations
import io, json, math, os
from datetime import date, timedelta
from typing import Any

import pandas as pd
import numpy as np
import rasterio
from rasterio.io import MemoryFile
import plotly.express as px
import requests
import streamlit as st
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="GeoRiskAI · Relaves", page_icon="⛏️", layout="wide")

# Coordenada referencial del depósito Las Tórtolas, sólo como punto de arranque del demo.
SAMPLE = {"nombre": "Las Tórtolas (referencia)", "lat": -33.121733, "lon": -70.735164, "comuna": "Colina, Región Metropolitana"}
CDSE_TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
CDSE_PROCESS_URL = "https://sh.dataspace.copernicus.eu/process/v1"
SERNAGEOMIN_LAYER = "https://services1.arcgis.com/OyjvVdFTl5hfSdX3/ArcGIS/rest/services/CDR_CHILE_AREAL_2025/FeatureServer/0"
INE_URBAN_LAYER = "https://services7.arcgis.com/5YrXOaoVCm5NKrty/arcgis/rest/services/MANZANAS_2024/FeatureServer/0"
INE_RURAL_LAYER = "https://services7.arcgis.com/5YrXOaoVCm5NKrty/arcgis/rest/services/ENTIDADES_2024/FeatureServer/0"


@st.cache_data(ttl=21600, show_spinner=False)
def load_tailings() -> tuple[list[dict], str]:
    """Descarga la capa areal nacional de SERNAGEOMIN con paginación ArcGIS."""
    meta = requests.get(SERNAGEOMIN_LAYER, params={"f": "json"}, timeout=45)
    meta.raise_for_status()
    metadata = meta.json()
    features: list[dict] = []
    offset = 0
    page_size = min(int(metadata.get("maxRecordCount", 2000)), 2000)
    while offset < 20000:
        params = {
            "where": "1=1", "outFields": "*", "returnGeometry": "true",
            "outSR": "4326", "geometryPrecision": 5, "f": "geojson",
            "resultOffset": offset, "resultRecordCount": page_size,
        }
        response = requests.get(f"{SERNAGEOMIN_LAYER}/query", params=params, timeout=90)
        response.raise_for_status()
        page = response.json()
        if "error" in page:
            raise RuntimeError(page["error"].get("message", "Error al consultar SERNAGEOMIN"))
        batch = page.get("features", [])
        features.extend(batch)
        if not page.get("exceededTransferLimit") and len(batch) < page_size:
            break
        if not batch:
            break
        offset += len(batch)
    if not features:
        raise RuntimeError("El servicio no devolvió polígonos de relaves.")
    fields = metadata.get("fields", [])
    display_field = metadata.get("displayField")
    return features, json.dumps({"fields": fields, "display_field": display_field})


def _field_for(properties: dict, fields: list[dict], kind: str) -> str | None:
    keys = list(properties)
    if kind == "name":
        needles = ("nombre relave", "nombre deposito", "deposito", "relave", "tranque", "embalse", "nombre")
    elif kind == "company":
        needles = ("empresa", "titular", "compania", "compañia", "minera", "propietario")
    else:
        needles = ("estado", "situacion", "operacion", "condicion")
    field_map = {str(f.get("name", "")).casefold(): str(f.get("alias", "")).casefold() for f in fields}
    scored = []
    for key in keys:
        label = (key.casefold() + " " + field_map.get(key.casefold(), ""))
        score = max((len(n) for n in needles if n in label), default=0)
        if score:
            # Exclude generic type fields from the display name.
            if kind == "name" and any(x in label for x in ("tipo", "metodo", "metodo")):
                score = 0
            scored.append((score, key))
    return max(scored)[1] if scored else None


def _coordinates(geometry: dict) -> tuple[float, float] | None:
    points = []
    def walk(item):
        if isinstance(item, (list, tuple)) and len(item) >= 2 and isinstance(item[0], (int, float)) and isinstance(item[1], (int, float)):
            points.append((float(item[0]), float(item[1])))
        elif isinstance(item, (list, tuple)):
            for child in item:
                walk(child)
    walk(geometry.get("coordinates", []))
    if not points:
        return None
    return ((min(p[1] for p in points) + max(p[1] for p in points)) / 2,
            (min(p[0] for p in points) + max(p[0] for p in points)) / 2)


def _prepare_sites(features: list[dict], metadata_json: str) -> list[dict]:
    meta = json.loads(metadata_json)
    fields = meta.get("fields", [])
    sites = []
    for index, feature in enumerate(features):
        props = feature.get("properties") or {}
        name_key = meta.get("display_field") if meta.get("display_field") in props else _field_for(props, fields, "name")
        company_key = _field_for(props, fields, "company")
        status_key = _field_for(props, fields, "status")
        name = str(props.get(name_key, "")).strip() if name_key else ""
        company = str(props.get(company_key, "")).strip() if company_key else ""
        status = str(props.get(status_key, "")).strip() if status_key else ""
        oid = next((props[k] for k in props if k.casefold() in ("objectid", "fid", "id")), index)
        center = _coordinates(feature.get("geometry") or {})
        label = " · ".join(v for v in (name or f"Depósito {oid}", company, status, f"ID {oid}") if v)
        feature["properties"] = {"nombre": name or f"Depósito {oid}", "empresa": company or "Titular no informado", "estado": status or "Estado no informado", "id": str(oid)}
        sites.append({"id": str(oid), "label": label, "name": name or f"Depósito {oid}", "company": company, "status": status, "center": center, "feature": feature})
    return sites


@st.cache_data(ttl=86400, show_spinner=False)
def load_ine_nearby(lat: float, lon: float, radius_km: int) -> tuple[list[dict], list[dict]]:
    """Consulta bloques censales urbanos y entidades rurales INE Censo 2024 por envolvente."""
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(.2, math.cos(math.radians(lat))))
    envelope = f"{lon-dlon},{lat-dlat},{lon+dlon},{lat+dlat}"
    result = []
    errors = []
    for url, layer_name, color in ((INE_URBAN_LAYER, "Manzanas urbanas INE 2024", "#00a6a6"),
                                   (INE_RURAL_LAYER, "Entidades rurales INE 2024", "#f39c3d")):
        features = []
        offset = 0
        try:
            while offset < 6000:
                params = {"where": "1=1", "outFields": "*", "returnGeometry": "true", "outSR": "4326",
                          "geometry": envelope, "geometryType": "esriGeometryEnvelope", "inSR": "4326",
                          "spatialRel": "esriSpatialRelIntersects", "geometryPrecision": 5,
                          "f": "geojson", "resultOffset": offset, "resultRecordCount": 2000}
                response = requests.get(f"{url}/query", params=params, timeout=75)
                response.raise_for_status()
                page = response.json()
                if "error" in page:
                    raise RuntimeError(page["error"].get("message", "ArcGIS devolvió un error"))
                batch = page.get("features", [])
                for feat in batch:
                    attrs = feat.get("properties") or {}
                    fid = next((attrs[k] for k in attrs if k.casefold() in ("objectid", "fid", "id")), "")
                    feat["properties"] = {"capa": layer_name, "id": str(fid)}
                    result.append({"type": "Feature", "geometry": feat.get("geometry"), "properties": feat["properties"], "color": color})
                features.extend(batch)
                if not page.get("exceededTransferLimit") and len(batch) < 2000:
                    break
                if not batch:
                    break
                offset += len(batch)
            if offset >= 6000:
                errors.append(f"{layer_name}: consulta limitada a 6.000 polígonos.")
        except Exception as e:
            errors.append(f"{layer_name}: {str(e)[:160]}")
    return result, errors

st.markdown("""
<style>
.block-container{padding-top:1.4rem;max-width:1440px}.hero{background:linear-gradient(120deg,#102f36,#14695f);padding:1.45rem 1.7rem;border-radius:18px;color:white;margin-bottom:1.1rem}.hero h1{margin:0;color:white}.hero p{margin:.35rem 0 0;color:#d7eeea}.risknote{background:#fff8e8;border-left:5px solid #e4a72f;padding:1rem 1.1rem;border-radius:8px;color:#493a18}.small{color:#73808a;font-size:.85rem}
</style>
<div class="hero"><h1>GeoRiskAI · Relaves</h1><p>Monitoreo satelital, comunidades expuestas y preparación ante emergencias</p></div>
""", unsafe_allow_html=True)

with st.spinner("Cargando polígonos del catastro nacional SERNAGEOMIN…"):
    try:
        _tailings_features, _tailings_metadata = load_tailings()
        sites = _prepare_sites(_tailings_features, _tailings_metadata)
        tailings_error = None
    except Exception as e:
        sites = []
        tailings_error = str(e)

with st.sidebar:
    st.header("Visor nacional de relaves")
    map_mode = st.radio("Vista", ["Todo Chile", "Entorno del depósito"], index=1)
    selected_site = None
    if sites:
        labels = [s["label"] for s in sites]
        default_ix = next((i for i, s in enumerate(sites) if "tortol" in s["name"].casefold()), 0)
        chosen = st.selectbox("Depósito (catastro SERNAGEOMIN)", labels, index=default_ix)
        selected_site = next(s for s in sites if s["label"] == chosen)
        if selected_site["center"]:
            lat, lon = selected_site["center"]
        else:
            lat, lon = SAMPLE["lat"], SAMPLE["lon"]
        st.caption(f"Titular: {selected_site['company'] or 'no informado'} · Estado: {selected_site['status'] or 'no informado'}")
    else:
        st.warning("No se logró descargar el catastro. Puedes consultar el mapa después o ingresar coordenadas manuales.")
        lat = st.number_input("Latitud", value=SAMPLE["lat"], format="%.6f")
        lon = st.number_input("Longitud", value=SAMPLE["lon"], format="%.6f")
    radius_km = st.slider("Radio para polígonos censales cercanos", 2, 30, 10)
    show_communities = st.checkbox("Mostrar manzanas y entidades censales INE", value=True)
    st.divider()
    st.subheader("Fechas satelitales")
    start = st.date_input("Desde", date(2019, 1, 1))
    end = st.date_input("Hasta", date.today())
    run_sat = st.button("Consultar Sentinel-1", type="primary", use_container_width=True)

# Ficha dinámica del depósito seleccionado
site_name = selected_site["name"] if selected_site else "Coordenadas manuales"
company_name = selected_site["company"] if selected_site and selected_site["company"] else "Sin dato del titular"
status_name = selected_site["status"] if selected_site and selected_site["status"] else "Sin dato de estado"
st.subheader("Ficha del depósito y entorno")
c1,c2,c3,c4 = st.columns(4)
c1.metric("Depósito", site_name)
c2.metric("Titular", company_name)
c3.metric("Estado", status_name)
c4.metric("Depósitos en catastro cargado", f"{len(sites):,}" if sites else "No disponible")
st.caption("Polígonos del Catastro Areal de Relaves SERNAGEOMIN (servicio actualizado a octubre de 2025; ficha del servicio consultada en 2026). La geometría sirve para screening y debe verificarse antes de decisiones técnicas.")

left,right = st.columns([1.25,1])
with left:
    st.markdown("#### Área del relave y entorno censal")
    if map_mode == "Entorno del depósito":
        nearby, nearby_errors = load_ine_nearby(lat, lon, radius_km) if show_communities else ([], [])
        map_center = [lat, lon]
        map_zoom = 12
    else:
        nearby, nearby_errors = [], []
        map_center = [-35.6, -71.4]
        map_zoom = 4
    fmap = folium.Map(location=map_center, zoom_start=map_zoom, control_scale=True, tiles=None)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles © Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community",
        name="Imagen satelital Esri", overlay=False, control=True, show=True, max_zoom=19,
    ).add_to(fmap)
    folium.TileLayer("OpenStreetMap", name="Mapa de calles", overlay=False, control=True, show=False).add_to(fmap)
    if sites:
        enriched = []
        for site in sites:
            feat = json.loads(json.dumps(site["feature"]))
            feat["properties"]["seleccionado"] = (site["id"] == selected_site["id"]) if selected_site else False
            enriched.append(feat)
        tailings_fc = {"type": "FeatureCollection", "features": enriched}
        def tailings_style(feature):
            chosen_feature = feature["properties"].get("seleccionado", False)
            return {"color": "#d43d51" if chosen_feature else "#5540a5",
                    "weight": 3 if chosen_feature else 1,
                    "fillColor": "#ef6474" if chosen_feature else "#7666c2",
                    "fillOpacity": .58 if chosen_feature else .28,
                    "dashArray": "" if chosen_feature else "4, 4"}
        folium.GeoJson(tailings_fc, name="Depósitos de relaves · SERNAGEOMIN",
                       style_function=tailings_style,
                       tooltip=folium.GeoJsonTooltip(fields=["nombre", "empresa", "estado"],
                                                     aliases=["Depósito", "Titular", "Estado"], sticky=True)).add_to(fmap)
    if nearby:
        urban_fc = {"type": "FeatureCollection", "features": [{k:v for k,v in f.items() if k != "color"} for f in nearby]}
        def census_style(feature):
            is_urban = "urbanas" in feature["properties"].get("capa", "")
            color = "#00a6a6" if is_urban else "#f39c3d"
            return {"color": color, "weight": 1.5, "fillColor": color, "fillOpacity": .22, "dashArray": "5, 3"}
        folium.GeoJson(urban_fc, name="Áreas censales cercanas · INE 2024",
                       style_function=census_style,
                       tooltip=folium.GeoJsonTooltip(fields=["capa"], aliases=["Capa censal"])).add_to(fmap)
    folium.CircleMarker([lat, lon], radius=4, color="#222", fill=True, fill_opacity=1,
                        tooltip=site_name).add_to(fmap)
    folium.LayerControl(collapsed=False).add_to(fmap)
    st_folium(fmap, height=570, use_container_width=True, returned_objects=[])
    if sites:
        st.caption("El mapa abre en imagen satelital Esri; en el control de capas puedes cambiar a calles. Morado: relaves nacionales. Rojo: depósito seleccionado. Turquesa: manzanas urbanas INE 2024. Naranjo: entidades rurales INE 2024. El borde discontinuo diferencia áreas censales.")
    if nearby_errors:
        st.warning("Algunas capas censales no se pudieron cargar: " + " · ".join(nearby_errors))
    if map_mode == "Entorno del depósito" and show_communities:
        st.caption(f"Unidades censales dibujadas en el radio consultado: {len(nearby):,}.")
    st.caption("Las manzanas y entidades delimitan unidades censales, no garantizan ocupación actual en cada parcela. La población debe interpretarse de forma agregada con datos INE.")
with right:
    st.markdown("#### Índice de priorización (demo)")
    st.markdown('<div class="risknote"><b>No es una probabilidad de colapso.</b><br>Este prototipo no tiene todavía población validada, escenarios hidráulicos ni etiquetas históricas suficientes para emitir un nivel de riesgo real.</div>',unsafe_allow_html=True)
    exposure = st.select_slider("Exposición preliminar ingresada por analista", options=["Sin datos","Baja","Media","Alta"], value="Sin datos")
    hazard = st.select_slider("Señales observadas verificadas", options=["Sin datos","Sin señal","Cambio a revisar","Anomalía confirmada"], value="Sin datos")
    st.metric("Resultado", "Pendiente" if "Sin datos" in (exposure,hazard) else "Revisión técnica requerida")
    st.write("**Componentes previstos**: exposición de personas aguas abajo; cercanía a cauces; señales satelitales; estado operacional; preparación y rutas de evacuación.")

st.divider()
st.header("Historial satelital Sentinel-1")
st.write("Sentinel-1 es radar y observa también de noche y con nubosidad. Cambios de retrodispersión pueden deberse a agua, humedad, vegetación, obras o geometría de observación; cada señal debe verificarse en terreno.")

@st.cache_data(ttl=3500, show_spinner=False)
def get_token(client_id: str, client_secret: str) -> str:
    r=requests.post(CDSE_TOKEN_URL,data={"grant_type":"client_credentials","client_id":client_id,"client_secret":client_secret},timeout=30)
    r.raise_for_status(); return r.json()["access_token"]

def request_s1(token: str, lat: float, lon: float, start_d: date, end_d: date, radius_km: int):
    # Aproximación de caja en grados para consulta; no reemplaza delimitación del depósito/cuenca.
    dlat=radius_km/111.0; dlon=radius_km/(111.0*max(.2,math.cos(math.radians(lat))))
    bbox=[lon-dlon,lat-dlat,lon+dlon,lat+dlat]
    evalscript='''//VERSION=3\nfunction setup(){return {input:[{bands:["VV","VH"]}],output:{bands:2,sampleType:"FLOAT32"}}}\nfunction evaluatePixel(s){return [s.VV,s.VH]}'''
    payload={"input":{"bounds":{"bbox":bbox,"properties":{"crs":"http://www.opengis.net/def/crs/EPSG/0/4326"}},"data":[{"type":"sentinel-1-grd","dataFilter":{"timeRange":{"from":start_d.isoformat()+"T00:00:00Z","to":end_d.isoformat()+"T23:59:59Z"},"mosaickingOrder":"leastCC"},"processing":{"orthorectify":True}}]},"output":{"width":512,"height":512,"responses":[{"identifier":"default","format":{"type":"image/tiff"}}]},"evalscript":evalscript}
    r=requests.post(CDSE_PROCESS_URL,headers={"Authorization":f"Bearer {token}"},json=payload,timeout=180)
    r.raise_for_status(); return r.content

if run_sat:
    secrets=st.secrets if hasattr(st,"secrets") else {}
    cid=secrets.get("CDSE_CLIENT_ID",os.getenv("CDSE_CLIENT_ID","")); csecret=secrets.get("CDSE_CLIENT_SECRET",os.getenv("CDSE_CLIENT_SECRET",""))
    if not cid or not csecret:
        st.warning("Para activar la consulta directa, configura CDSE_CLIENT_ID y CDSE_CLIENT_SECRET en .streamlit/secrets.toml. El registro de OAuth es gratuito en Copernicus Data Space. También puedes cargar GeoTIFF históricos abajo.")
    elif end < start:
        st.error("La fecha final debe ser posterior a la inicial.")
    else:
        # Ocho ventanas semestrales distribuidas en todo el intervalo histórico.
        window=180; total=max(0,(end-start).days); n=min(8,max(1,total//window+1))
        if n == 1: anchors=[start]
        else: anchors=[start+timedelta(days=round(i*(total-window)/(n-1))) for i in range(n)]
        spans=[(a,min(a+timedelta(days=window),end)) for a in anchors]
        rows=[]
        try:
            token=get_token(cid,csecret)
            with st.spinner("Consultando escenas Sentinel-1…"):
                for a,b in spans:
                    try:
                        raw=request_s1(token,lat,lon,a,b,radius_km)
                        rows.append({"Periodo":f"{a:%Y-%m} – {b:%Y-%m}","GeoTIFF":raw,"Estado":"Escena/procesamiento disponible"})
                    except Exception as e:
                        rows.append({"Periodo":f"{a:%Y-%m} – {b:%Y-%m}","GeoTIFF":None,"bbox":None,"Estado":f"Sin resultado o error: {str(e)[:140]}"})
            st.session_state["s1_rows"]=rows
        except Exception as e: st.error(f"No se pudo autenticar con Copernicus: {e}")

rows=st.session_state.get("s1_rows",[])
if rows:
    statuses=pd.DataFrame([{k:v for k,v in x.items() if k!="GeoTIFF"} for x in rows])
    st.dataframe(statuses,use_container_width=True,hide_index=True)
    valid=[x for x in rows if x["GeoTIFF"]]
    if valid:
        labels=[x["Periodo"] for x in valid]
        chosen_label=st.selectbox("Periodo para visualizar",labels)
        chosen=next(x for x in valid if x["Periodo"]==chosen_label)
        st.download_button("Descargar GeoTIFF VV/VH",chosen["GeoTIFF"],file_name=f"sentinel1_{chosen['Periodo'][:7]}.tif",mime="image/tiff")
        try:
            with MemoryFile(chosen["GeoTIFF"]) as mem:
                with mem.open() as src:
                    vv=src.read(1).astype("float32"); vh=src.read(2).astype("float32")
            vv_db=10*np.log10(np.maximum(vv,1e-8)); vh_db=10*np.log10(np.maximum(vh,1e-8))
            candidate=(vv_db < -17) & np.isfinite(vv_db)
            proxy=float(candidate.sum()/np.isfinite(vv_db).sum()*100)
            m1,m2=st.columns(2)
            m1.metric("Pixeles de retrodispersión baja",f"{proxy:.1f}%","proxy exploratorio")
            m2.caption("Umbral visual heurístico VV < −17 dB. Puede confundir agua con suelo liso, sombra radar o superficies construidas; no es nivel/altura de inundación.")
            fig=px.imshow(vv_db, color_continuous_scale="Gray", origin="upper", aspect="auto", title=f"Sentinel-1 VV (dB) · {chosen_label}")
            fig.update_layout(coloraxis_colorbar_title="dB",height=430)
            st.plotly_chart(fig,use_container_width=True)
            hist=[]
            for item in valid:
                with MemoryFile(item["GeoTIFF"]) as mem:
                    with mem.open() as src: arr=src.read(1).astype("float32")
                db=10*np.log10(np.maximum(arr,1e-8)); validpx=np.isfinite(db)
                hist.append({"Periodo":item["Periodo"],"Pixeles bajo -17 dB (%)":float(((db < -17)&validpx).sum()/validpx.sum()*100)})
            st.plotly_chart(px.line(pd.DataFrame(hist),x="Periodo",y="Pixeles bajo -17 dB (%)",markers=True,title="Cambio temporal de señal baja (proxy, no inundación)"),use_container_width=True)
        except Exception as e: st.warning(f"La escena se descargó, pero no se pudo previsualizar: {e}")
        st.info("La app visualiza retrodispersión y muestra un proxy temporal. Una inundación requiere clasificación validada con terreno, DEM, lluvia, máscara histórica de agua y análisis de expertos.")

st.markdown("#### Alternativa: cargar productos históricos")
uploads=st.file_uploader("Sube GeoTIFF Sentinel-1 o una tabla CSV con fecha y variables ya procesadas",type=["tif","tiff","csv"],accept_multiple_files=True)
if uploads:
    for f in uploads:
        st.success(f"Archivo recibido: {f.name} · {f.size/1024:.1f} KB")
        if f.name.lower().endswith(".csv"):
            try:
                df=pd.read_csv(f); st.dataframe(df.head(100),use_container_width=True)
                if {"fecha","agua_proxy"}.issubset(df.columns):
                    st.plotly_chart(px.line(df,x="fecha",y="agua_proxy",title="Serie proxy de agua (requiere validación)"),use_container_width=True)
            except Exception as e: st.error(f"No se pudo leer CSV: {e}")

st.divider()
st.header("Aprendizaje supervisado: protocolo seguro")
st.markdown("El modelo aprende sólo cuando hay ejemplos etiquetados con evidencia verificable. La ausencia de noticias o de una señal satelital **no** equivale a un caso seguro.")
with st.expander("Plantilla y entrenamiento experimental"):
    template=pd.DataFrame(columns=["deposito_id","fecha","evento_confirmado","fuente_evidencia","lluvia_72h_mm","agua_proxy","cambio_retrodispersion","personas_aguas_abajo","distancia_cauce_m","grupo_deposito"])
    st.download_button("Descargar plantilla CSV",template.to_csv(index=False),"plantilla_etiquetado_relaves.csv","text/csv")
    st.write("Etiqueta `evento_confirmado` con incidentes o anomalías documentadas por fuente técnica. Mantén fuente, fecha y confianza; separa train/test por depósito para evitar que el modelo sólo memorice un sitio.")
    training_file=st.file_uploader("Dataset etiquetado CSV",type=["csv"],key="train_csv")
    if training_file and st.button("Validar y entrenar modelo experimental"):
        try:
            from modelo_supervisado import entrenar_por_deposito
            result=entrenar_por_deposito(pd.read_csv(training_file))
            if result["ok"]:
                st.success(f"Evaluación agrupada por depósito: {result['n_sites']} depósitos · ROC AUC {result['auc']:.2f} · sensibilidad {result['recall']:.2f} · precisión {result['precision']:.2f}")
                st.caption("Modelo exploratorio; métricas con conjunto de prueba por depósito. No es probabilidad de falla ni debe usarse para activar emergencias.")
            else:
                st.warning(result["message"])
        except Exception as e: st.error(f"No se pudo entrenar: {e}")

st.header("Cómo se financia y gobierna")
colA,colB,colC=st.columns(3)
colA.markdown("**Piloto patrocinado**\n\nContrato anual de monitoreo y preparación con minera, primero para un depósito y comunas vecinas.")
colB.markdown("**Acceso comunitario gratuito**\n\nAlertas, reportes básicos y rutas de información financiados como beneficio público; no cobrar a las personas afectadas.")
colC.markdown("**Independencia verificable**\n\nMetodología pública, auditoría externa/universitaria, trazabilidad de cambios y publicación de limitaciones. El patrocinador no puede editar el nivel técnico.")
st.caption("La plataforma ayuda a priorizar análisis y coordinación. Alarmas, evacuaciones, declaraciones de seguridad y mapas de inundación por falla deben quedar en manos de autoridades y especialistas competentes.")

with st.expander("Fuentes y siguientes integraciones"):
    st.markdown("- [SERNAGEOMIN: Catastro areal nacional de relaves](https://services1.arcgis.com/OyjvVdFTl5hfSdX3/ArcGIS/rest/services/CDR_CHILE_AREAL_2025/FeatureServer)\n- [INE: manzanas urbanas Censo 2024](https://services7.arcgis.com/5YrXOaoVCm5NKrty/arcgis/rest/services/MANZANAS_2024/FeatureServer)\n- [INE: entidades rurales Censo 2024](https://services7.arcgis.com/5YrXOaoVCm5NKrty/arcgis/rest/services/ENTIDADES_2024/FeatureServer)\n- [Copernicus Data Space: Sentinel Hub y autenticación OAuth](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Overview/Authentication.html)\n- [Copernicus: ejemplo Sentinel-1 GRD](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Process/Examples/S1GRD.html)\n- [Copernicus: catálogo STAC](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Catalog.html)\n- [Consejo Minero: ficha Las Tórtolas](https://consejominero.cl/operaciones/las-tortolas/)\n- [Municipalidad de Colina: ejercicio de emergencia con comunidades](https://www.colina.cl/colina-y-tiltil-reforzaron-protocolos-de-emergencia-ante-eventuales-eventos-en-relaves-las-tortolas/)")
