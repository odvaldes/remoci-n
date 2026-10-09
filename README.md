# GeoRiskAI Sentinel — Remoción en masa por flujos

## Instalación en GitHub y Streamlit Cloud

Subir **todos** los archivos de esta carpeta a la misma carpeta de GitHub:

- `app.py` (archivo principal que se selecciona en Streamlit Cloud)
- `modelo_ird.py` (escalas y cálculo)
- `fuentes_geo.py` (conexiones automáticas a fuentes geoespaciales)
- `requirements.txt` (dependencias)
- `README.md` (instrucciones)

En Streamlit Cloud seleccionar `app.py` como **Main file path** (o `remocion_masa/app.py` si están dentro de esa carpeta). No subir el ZIP como único archivo.

## Novedades de esta versión

1. Al dibujar o cargar un polígono, la app **intenta consultar automáticamente** el DEM Copernicus GLO-30 mediante COG públicos en AWS. Descarga/lee las teselas necesarias y recorta el área; no descarga un DEM nacional.
2. Calcula pendientes y elevaciones usando ese DEM, si la consulta tiene éxito. Permite subir manualmente un DEM GeoTIFF si falla.
3. Consulta ESA WorldCover a través del catálogo STAC de Microsoft Planetary Computer para mostrar la distribución de clases de cobertura en el polígono. No presupone que esa cobertura equivalga a la clasificación de escorrentía del manual MDSF.
4. Conserva los seis factores de amenaza del manual, incluyendo valores manuales cuando no hay fuente confiable. El suelo de fundación **no se infiere desde satélite**.
5. Conserva las ponderaciones propias de GeoRiskAI: 66,7% amenaza; 33,3% vulnerabilidad. Dentro de vulnerabilidad: 75% materialidad; 25% antigüedad normativa.
6. Exporta ficha JSON con las fuentes geográficas consultadas.

## Limitaciones importantes

- La combinación de condicionantes de generación y área de alcance sigue siendo una **hipótesis exploratoria configurable**, por defecto 50/50, pendiente de verificar en la metodología complementaria del MDSF. **No es un IRD oficial.**
- La clasificación de WorldCover **no se transforma automáticamente** en cobertura hidrológica del manual. El evaluador selecciona cobertura y permeabilidad con evidencia adecuada.
- No hay todavía descarga automática del catastro SERNAGEOMIN ni delimitación validada de abanicos aluviales. Los eventos históricos deben incorporarse con un protocolo de validación espacial y temporal, no como una capa de amenaza intercambiable.
- La pendiente máxima depende de la resolución, la delimitación y la calidad del DEM. La evaluación requiere respetar la celda de análisis definida en el manual.
- La consulta remota necesita Internet, que el servidor permita abrir COG HTTP y que los proveedores estén disponibles. Pueden existir límites de transferencia, tiempo o acceso. Las consultas automáticas se restringen a polígonos de extensión máxima aproximada de 18 km.
- **El código fue comprobado sintácticamente, pero no se ejecutó una consulta real a las APIs desde este entorno sin acceso de red.** Si el proveedor modifica endpoints o permisos puede requerir ajustes.

## Ejecutar localmente

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Datos y trazabilidad

- Copernicus DEM GLO-30: `https://registry.opendata.aws/copernicus-dem/`
- ESA WorldCover: `https://esa-worldcover.org/en/data-access`
- Planetary Computer STAC: `https://planetarycomputer.microsoft.com/api/stac/v1`
- SERNAGEOMIN: `https://portalgeomin.sernageomin.cl/`

El módulo se utiliza para evaluación preliminar de inversiones, no para reemplazar estudios geotécnicos, mapas oficiales de peligro, permisos ni decisiones de seguridad.

## Detección automática de taludes, cauces y candidatos a abanicos (v3)

Después de seleccionar el polígono y obtener el DEM, pulsar **Detectar taludes, cauces y posibles abanicos**. `deteccion_terreno.py` calcula distancias mínimas del polígono a taludes potenciales (pendiente >=30° y relieve local >=8 m), consulta cauces de OpenStreetMap mediante Overpass, y obtiene una aproximación de drenaje topográfico mediante concavidad del DEM. Detecta *candidatos* a abanicos mediante condiciones heurísticas de pendiente moderada, cercanía a ladera y convergencia; **NO confirma abanicos aluviales ni asigna automáticamente su puntaje de amenaza**. Las distancias y el indicador se incorporan a la ficha JSON.

**Limitaciones:** las distancias se refieren a las geometrías disponibles dentro del DEM y/o a la cobertura OSM; no implican inventario exhaustivo. Los cauces OSM no son necesariamente cauces de flujo aluvional y su ausencia no descarta amenaza. La distancia a cauce **no reemplaza** el subfactor MDSF "distancia a intervenciones del cauce". Para análisis riguroso se requiere DEM con área de aporte aguas arriba, inventario oficial de abanicos/cauces, delimitación geomorfológica y verificación experta. No se han probado las APIs remotas desde este entorno.
