# GeoRiskAI Sentinel — Remoción en masa por flujos

Prototipo para dibujar o importar polígonos, caracterizar superficie y analizar pendientes mediante un DEM GeoTIFF. El mapa puede superponer áreas de riesgo del PRC de La Serena, una capa vectorial regional para Coquimbo y capas de SERNAGEOMIN de susceptibilidad/eventos.

## Capas territoriales integradas
- **La Serena:** KMZ municipal de zonas de riesgo y fajas no edificables del PRC 2020 (el municipio lo califica como referencial).
- **Coquimbo:** consulta a la capa `IPT_04_PRC_Coquimbo_R` del servicio de información territorial. El PRC actualizado está vigente desde el 5 de enero de 2026; como la capa vectorial no identifica claramente en sus metadatos la versión del instrumento, verificarla contra los planos y ordenanza vigentes antes de usarla normativamente.
- **SERNAGEOMIN:** consulta de las capas publicadas en el mapa de susceptibilidad de flujos de detritos de Coquimbo, más el catastro de eventos históricos (1962–2021). El catastro representa eventos registrados, no una zonificación de peligro actual.
- La interfaz deja a mano los informes/cartas SERNAGEOMIN Coquimbo Norte (IR-18-68) y Coquimbo Sur (IR-21-88), ambos de referencia regional a escala 1:250.000.
- El cruce solo calcula intersección geométrica con las capas que respondan. No reemplaza estudios fundados, revisión DOM, geotecnia ni una determinación oficial de peligro o riesgo.

Las capas se consultan en línea y se almacenan en caché por 24 horas en la sesión de la aplicación. Streamlit debe poder acceder a `mapas.laserena.cl`, `services6.arcgis.com`, `services3.arcgis.com` y `www.arcgis.com`. Si una fuente no está disponible, la app lo muestra y sigue con las capas restantes.

## Despliegue en Streamlit Community Cloud
1. Sube `app.py` y `requirements.txt` a la raíz de un repositorio GitHub.
2. En https://share.streamlit.io selecciona **Create app** y el repositorio.
3. Main file path: `app.py`.
4. Abre el mapa y dibuja un polígono o sube un GeoJSON (EPSG:4326).
5. Para calcular pendientes, sube un DEM GeoTIFF que cubra el polígono. También se admite `DEM_PATH` como variable de entorno o Streamlit Secret si el archivo existe en el servidor.

## Limitaciones deliberadas
- **No calcula el IRD oficial MDSF**. Faltan capas validadas, variables de vulnerabilidad y resiliencia y la integración verificada de escalas y ecuación oficial.
- La integración de capas no cambia las escalas ni los cálculos del modelo; los polígonos se muestran como fuentes cartográficas independientes.
- Confirmar con cada organismo las condiciones de reproducción, redistribución y uso comercial de los mapas/capas antes de ofrecer el producto por suscripción. El manual MDSF de remoción en masa usado por el prototipo indica licencia BY-NC-ND; el código y el servicio comercial requieren revisar derechos y obtener autorización si corresponde.
- No descarga imágenes satelitales ni DEM automáticamente. El mapa base es de visualización, no una fuente de datos de pendiente.
- Pendientes calculadas en grados; resultados sensibles a resolución, calidad y bordes del DEM. Se requiere comprobar la unidad/celda de análisis del manual.
- La lectura del DEM cargado se realiza en memoria; para producción nacional usar COG por ventanas, almacenamiento remoto y límites de área.
- Para proyectos en Chile insular o zonas fuera del continente, revisar el aviso de ubicación; el mapa no está restringido a Chile continental.

## Desarrollo posterior
Validar la versión de Coquimbo contra sus planos PRC 2026; verificar disponibilidad, escala, fecha y licencia de la capa SERNAGEOMIN; incorporar los mapas SERNAGEOMIN Norte y Sur como capas vectoriales o ráster georreferenciadas con permiso de uso; integrar COG nacional, cobertura Sentinel-2, cauces y abanicos validados; y contrastar el motor con el software MDSF.
