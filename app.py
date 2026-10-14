"""GeoRiskAI Relaves — prototipo de monitoreo y exposición (no evaluación ingenieril)."""
from __future__ import annotations
import io, math, os
from datetime import date, timedelta
from typing import Any

import pandas as pd
import numpy as np
import rasterio
from rasterio.io import MemoryFile
import plotly.express as px
import requests
import streamlit as st

st.set_page_config(page_title="GeoRiskAI · Relaves", page_icon="⛏️", layout="wide")

# Coordenada referencial del depósito Las Tórtolas, sólo como punto de arranque del demo.
SAMPLE = {"nombre": "Las Tórtolas (referencia)", "lat": -33.121733, "lon": -70.735164, "comuna": "Colina, Región Metropolitana"}
CDSE_TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
CDSE_PROCESS_URL = "https://sh.dataspace.copernicus.eu/process/v1"

st.markdown("""
<style>
.block-container{padding-top:1.4rem;max-width:1440px}.hero{background:linear-gradient(120deg,#102f36,#14695f);padding:1.45rem 1.7rem;border-radius:18px;color:white;margin-bottom:1.1rem}.hero h1{margin:0;color:white}.hero p{margin:.35rem 0 0;color:#d7eeea}.risknote{background:#fff8e8;border-left:5px solid #e4a72f;padding:1rem 1.1rem;border-radius:8px;color:#493a18}.small{color:#73808a;font-size:.85rem}
</style>
<div class="hero"><h1>GeoRiskAI · Relaves</h1><p>Monitoreo satelital, comunidades expuestas y preparación ante emergencias</p></div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.header("Área de análisis")
    target = st.selectbox("Depósito", [SAMPLE["nombre"], "Ingresar coordenadas"])
    if target == SAMPLE["nombre"]:
        lat, lon = SAMPLE["lat"], SAMPLE["lon"]
        st.caption(SAMPLE["comuna"])
    else:
        lat = st.number_input("Latitud", value=-33.163, format="%.6f")
        lon = st.number_input("Longitud", value=-70.754, format="%.6f")
    radius_km = st.slider("Radio de análisis", 2, 30, 10)
    st.divider()
    st.subheader("Fechas satelitales")
    start = st.date_input("Desde", date(2019, 1, 1))
    end = st.date_input("Hasta", date.today())
    run_sat = st.button("Consultar Sentinel-1", type="primary", use_container_width=True)

# Open dataset records and features
st.subheader("Ficha del depósito y entorno")
c1,c2,c3,c4 = st.columns(4)
c1.metric("Sitio", "Las Tórtolas")
c2.metric("Comuna", "Colina")
c3.metric("Operación reportada", "Desde 1992")
c4.metric("Población cercana", "Requiere capa censal")
st.caption("La ficha se basa en fuentes públicas. Los datos de operación, diseño y clasificación deben contrastarse con el catastro vigente y reportes de la autoridad antes de tomar decisiones.")

left,right = st.columns([1.25,1])
with left:
    st.markdown("#### Vista espacial")
    st.map(pd.DataFrame({"lat":[lat],"lon":[lon]}), zoom=10)
    st.markdown("**Capas para integrar**")
    st.write("• Polígono del depósito (SERNAGEOMIN)  • localidades y población (INE/WorldPop)  • cauces y red vial  • modelo digital de elevación  • zonas de amenaza y evacuación")
    st.caption("El mapa base del prototipo muestra el punto referencial. Para un análisis oficial hay que cargar el polígono actualizado del depósito y capas verificadas de comunidades.")
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
                        rows.append({"Periodo":f"{a:%Y-%m} – {b:%Y-%m}","GeoTIFF":raw,"bbox":bbox,"Estado":"Escena/procesamiento disponible"})
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
    st.markdown("- [SERNAGEOMIN: Visores mineros y plataforma pública de relaves](https://www.sernageomin.cl/visores-mineros/)\n- [Copernicus Data Space: Sentinel Hub y autenticación OAuth](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Overview/Authentication.html)\n- [Copernicus: ejemplo Sentinel-1 GRD](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Process/Examples/S1GRD.html)\n- [Copernicus: catálogo STAC](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Catalog.html)\n- [Consejo Minero: ficha Las Tórtolas](https://consejominero.cl/operaciones/las-tortolas/)\n- [Municipalidad de Colina: ejercicio de emergencia con comunidades](https://www.colina.cl/colina-y-tiltil-reforzaron-protocolos-de-emergencia-ante-eventuales-eventos-en-relaves-las-tortolas/)")
