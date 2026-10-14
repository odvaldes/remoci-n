# GeoRiskAI Sentinel — Remoción en masa por flujos

Prototipo para dibujar o importar polígonos y generar una ficha preliminar de remoción en masa. Calcula automáticamente pendiente desde Copernicus GLO-30, cobertura desde Copernicus CGLS 2019, clase agrícola desde CIREN y cruces espaciales disponibles. El mapa también superpone PRC, CITSU SHOA Coquimbo–La Serena, peligro volcánico publicado en ArcGIS y capas disponibles de inundación DGA/MOP. Calcula el porcentaje del predio en cota topográfica ≤30 m a partir del DEM.

## Capas territoriales integradas
- **Tsunami:** CITSU SHOA Coquimbo–La Serena, 2.ª edición 2015, en KMZ. La capa representa inundación modelada; revisar en SHOA si hay una edición posterior antes de utilizarla.
- **Cota 30:** máscara del DEM Copernicus GLO-30 para elevaciones ≤30 m dentro del predio, mostrada en mapa y resumida como porcentaje/superficie. Es una referencia topográfica, no una línea oficial de evacuación.
- **Peligro volcánico:** capa poligonal nacional publicada en un servicio ArcGIS asociado a gestión del riesgo volcánico. Es indicativa; contrastar con las cartas específicas de SERNAGEOMIN, cada una con su escala y cobertura.
- **Inundación:** mapa DGA de amenaza en cuenca Mataquito (2025) y puntos referenciales DOH/SIALL donde el servicio tiene cobertura (principalmente área metropolitana de Santiago). No existe cobertura homogénea nacional en estas capas consultadas.
- **La Serena:** KMZ municipal de zonas de riesgo y fajas no edificables del PRC 2020 (el municipio lo califica como referencial).
- **Coquimbo:** consulta a la capa `IPT_04_PRC_Coquimbo_R` del servicio de información territorial. El PRC actualizado está vigente desde el 5 de enero de 2026; como la capa vectorial no identifica claramente en sus metadatos la versión del instrumento, verificarla contra los planos y ordenanza vigentes antes de usarla normativamente.
- **SERNAGEOMIN:** consulta de las capas publicadas en el mapa de susceptibilidad de flujos de detritos de Coquimbo, más el catastro de eventos históricos (1962–2021). El catastro representa eventos registrados, no una zonificación de peligro actual.
- La interfaz deja a mano los informes/cartas SERNAGEOMIN Coquimbo Norte (IR-18-68) y Coquimbo Sur (IR-21-88), ambos de referencia regional a escala 1:250.000.
- El cruce solo calcula intersección geométrica con las capas que respondan. No reemplaza estudios fundados, revisión DOM, geotecnia ni una determinación oficial de peligro o riesgo.

Las fuentes se consultan en línea y se almacenan en caché. Streamlit debe tener salida de red a Copernicus (AWS/Zenodo), CIREN ArcGIS, OpenStreetMap Overpass, SHOA, DGA/MOP, PRC y servicios ArcGIS. Si una fuente falla o no cubre el polígono, esa variable queda sin puntaje; no se rellena con cero.

## Despliegue en Streamlit Community Cloud
1. Sube `app.py` y `requirements.txt` a la raíz de un repositorio GitHub.
2. En https://share.streamlit.io selecciona **Create app** y el repositorio.
3. Main file path: `app.py`.
4. Abre el mapa y dibuja un polígono o sube un GeoJSON (EPSG:4326).
5. La app seleccionará automáticamente una tesela Copernicus GLO-30 si toda la geometría cabe dentro de una tesela de 1°. Puede cargarse un DEM propio para reemplazarla.

## Limitaciones deliberadas
- **No calcula el IRD oficial MDSF**. Faltan capas validadas, variables de vulnerabilidad y resiliencia y la integración verificada de escalas y ecuación oficial.
- La integración de amenazas no cambia las escalas ni los cálculos del modelo; los polígonos se muestran como fuentes cartográficas independientes.
- Confirmar con cada organismo las condiciones de reproducción, redistribución y uso comercial de los mapas/capas antes de ofrecer el producto por suscripción. El manual MDSF de remoción en masa usado por el prototipo indica licencia BY-NC-ND; el código y el servicio comercial requieren revisar derechos y obtener autorización si corresponde.
- GLO-30 es un DSM de 30 m, no un modelo bare-earth; vegetación y edificios pueden afectar pendiente. CGLS usado aquí es 100 m y referencia 2019.
- El cruce entre capacidad agrícola CIREN y clase geotécnica A–F es solo una regla experimental; capacidad agrícola no mide Vs30, SPT ni resistencia. No debe usarse para decisiones de seguros, construcción o emergencia.
- El proxy de permeabilidad y las categorías de cobertura resumen clases cartográficas para completar la tabla MDSF; requieren calibración y validación local.
- Distancia a cauces/obras usa OpenStreetMap, con cobertura incompleta. La ausencia de un objeto mapeado no prueba que no exista. Abanicos aluviales y distancia a taludes no se puntúan automáticamente si las fuentes no permiten medirlos con fiabilidad.
- La lectura del DEM Copernicus se hace como COG remoto; para producción, incorporar mosaico regional, manejo de límites y reintentos.
- Para proyectos en Chile insular o zonas fuera del continente, revisar el aviso de ubicación; el mapa no está restringido a Chile continental.

## Desarrollo posterior
Validar la versión de Coquimbo contra sus planos PRC 2026; verificar disponibilidad, escala, fecha y licencia de la capa SERNAGEOMIN; incorporar los mapas SERNAGEOMIN Norte y Sur como capas vectoriales o ráster georreferenciadas con permiso de uso; ampliar CITSU con el catálogo vigente de SHOA; sustituir proxies por estudios geotécnicos y cartografía oficial nacional de inundación, cauces, abanicos/taludes e intervenciones hidráulicas; calibrar cada cruce en Chile; y contrastar el motor con el software MDSF.
