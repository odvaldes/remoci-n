# Fuentes cartográficas integradas

Revisión de fuentes: 14 de octubre de 2026. Las capas se consultan en línea en cada sesión y quedan en caché por 24 horas.

| Capa | Fuente | Qué representa | Precaución |
|---|---|---|---|
| PRC La Serena 2020 | Visor SIG municipal y KMZ enlazado por el visor | Zonas de riesgo y fajas no edificables | El propio municipio califica el mapa como referencial. |
| PRC Coquimbo | Servicio `Planificador_Territorial_Coquimbo_WFL1`, capa `IPT_04_PRC_Coquimbo_R` | Polígonos de áreas de riesgo | La actualización del PRC entró en vigencia el 05-01-2026, pero la capa vectorial no indica claramente en su descripción la versión del PRC. Confirmar con la Municipalidad/SECPLAN antes de usarla normativamente. |
| SERNAGEOMIN Coquimbo | Web map ArcGIS “Mapa de Peligro Geológico de Coquimbo (Susceptibilidad de Flujo de detritos)” | Capas vectoriales publicadas de susceptibilidad y remociones asociadas | No confundir susceptibilidad con riesgo ni asumir que el mapa representa amenaza actual en tiempo real. |
| SERNAGEOMIN Coquimbo Norte | Informe IR-18-68, mapa regional escala 1:250.000 | Peligros por remociones en masa | Enlace de consulta/descarga; no se vectoriza el PDF dentro de esta versión. |
| SERNAGEOMIN Coquimbo Sur | Informe IR-21-88, mapa regional escala 1:250.000 | Peligro de remociones en masa y zonas potencialmente inundables | Enlace de consulta/descarga; no se vectoriza el PDF dentro de esta versión. |
| Catastro histórico SERNAGEOMIN | FeatureServer “Chile - Remociones Masa”, eventos 1962–2021 | Eventos históricos registrados | Es inventario de ocurrencias, no una zonificación de peligro. |

## Enlaces oficiales o de servicio

- La Serena: <https://mapas.laserena.cl/mapas/riesgos%20_NoEdificables/>
- PRC Coquimbo vigente: <https://www.bcn.cl/leychile/Navegar?idNorma=1219776>
- Web map SERNAGEOMIN Coquimbo: <https://www.arcgis.com/apps/mapviewer/index.html?webmap=bd82ae84d40643019878dea882335381>
- Coquimbo Norte IR-18-68: <https://catalogobiblioteca.sernageomin.cl/Archivos/15633%20-texto%20y%20mapa-red.pdf>
- Coquimbo Sur IR-21-88: <https://portalgeo.sernageomin.cl/Informes_PDF_Nac/RM-2021-01.pdf>
- Catastro de eventos 1962–2021: <https://services3.arcgis.com/uZrwedu11XCCdHk1/arcgis/rest/services/M5T7___Mapa___Remociones_en_Masa__Chile_1962_2021__WFL1/FeatureServer>

## Uso y derechos

Las capas se muestran como referencias independientes y no modifican los cálculos del modelo. Antes de ofrecer el producto por suscripción, confirmar permisos de acceso, redistribución, almacenamiento en caché y uso comercial con cada titular. El manual MDSF 2025 de remoción en masa utilizado por el prototipo indica licencia Creative Commons BY-NC-ND; el uso comercial y cualquier adaptación de escalas deben revisarse y contar con autorización cuando corresponda.

El mapa es de cribado. No reemplaza el PRC oficial, los estudios fundados de riesgo, la revisión de la DOM ni el análisis geológico/geotécnico en terreno.

## Variables automáticas experimentales añadidas

| Variable | Fuente/método | Límite de interpretación |
|---|---|---|
| Pendiente | Copernicus DEM GLO-30, COG remoto AWS; estadístico máximo y percentil 95 sobre el polígono | DSM global de 30 m; no reemplaza topografía de detalle.
| Cobertura | Copernicus Global Land Cover 100 m, año 2019 (CGLS v3); clase mayoritaria | Resolución 100 m y fecha histórica; un predio pequeño puede no tener píxeles válidos.
| Suelo de fundación | CIREN, capacidad de uso agrícola de Coquimbo 2022 (campo `textcaus`) con cruce experimental I–VIII a puntaje MDSF A–F | No es geotecnia ni clase sísmica. Cruce no validado y no usar para decisiones críticas.
| Escorrentía | Tabla MDSF alimentada con pendiente p95, cobertura CGLS agregada y permeabilidad supuesta desde clase agrícola | La permeabilidad no se mide en la capa agrícola; puntaje experimental.
| Cauce / intervención | Distancias a objetos de hidrografía/obras publicados en OpenStreetMap, consulta Overpass | Inventario voluntario incompleto; no hallar objeto no prueba ausencia.
| Abanicos / taludes | Sin capa nacional adecuada para inferirlos automáticamente en esta versión | Mantener el factor sin puntaje cuando no hay evidencia; no inferir “fuera de abanico”.

Copernicus GLO-30: <https://registry.opendata.aws/copernicus-dem/>  · CGLS 2019: <https://land.copernicus.eu/en/products/global-dynamic-land-cover/copernicus-global-land-service-land-cover-100m-collection-3-epoch-2015-2019-globe> · CIREN Suelos Agrológicos: <https://esri.ciren.cl/server/rest/services/IDEMINAGRI/SUELOS_AGROLOGICOS/MapServer> · OSM Overpass: <https://overpass-api.de/>.

## Amenazas nuevas del visor (implementación 14-10-2026)

| Amenaza | Capa integrada | Alcance y advertencia |
|---|---|---|
| Tsunami | SHOA CITSU Coquimbo–La Serena, KMZ 2.ª edición (2015) | Se superpone al mapa y cruza con el predio. Corroborar edición actual en SHOA; el catálogo SHOA publica cartas por localidad, no una sola cobertura vectorial nacional.
| Cota 30 | Cálculo GLO-30 de píxeles ≤30 m dentro del predio dibujado | Indicador topográfico automático dentro del área analizada; no equivale a CITSU, zona de inundación ni línea oficial de seguridad.
| Volcán | Servicio ArcGIS nacional `Riesgo_Volcánico/FeatureServer/6` | Capa referencial para cobertura de amenaza; validar contra cartas de peligros SERNAGEOMIN por volcán, con fechas y escalas diferentes.
| Inundación fluvial | DGA, Mapa de Amenaza de Inundación del río Mataquito (2025), KMZ; DOH/SIALL puntos referenciales de inundación | La capa DGA cubre Mataquito; los puntos DOH/SIALL publicados no son una cobertura nacional. Los PRC cargados pueden aportar zonificación local adicional.

## Suelo de fundación: fuentes consultadas

No se identificó una base nacional homogénea y abierta de clases geotécnicas de fundación mantenida por MINVU. MINVU/DITEC publica manuales técnicos sobre suelos orgánicos, licuables, expansivos, caracterización y construcción en suelos salinos, entre otros; son lineamientos, no un mapa parcelario. CIREN mantiene estudios agrológicos y capacidad de uso del suelo, que no miden directamente Vs30, N-SPT, resistencia o parámetros de diseño de fundaciones. SERNAGEOMIN tiene estudios locales de suelo de fundación y microzonificación (por ejemplo Valdivia, Concepción, Iquique y Alto Hospicio), publicados individualmente en su catálogo.

En el visor, el dato CIREN se conserva como categoría agrícola. El cruce a puntaje MDSF es una analogía de prototipo, no clase geotécnica. La conversión debe ser calibrada o reemplazada por estudio de mecánica de suelos antes de usarla en seguros, diseño o decisiones oficiales.

Referencias para suelos: [MINVU DITEC, manuales técnicos](https://www.minvu.gob.cl/ditec/manuales-tecnicos-ditec/) · [CIREN Suelo](https://www.ciren.cl/suelo) · [Catálogo de publicaciones SERNAGEOMIN](https://portalsdnmext.sernageomin.cl/publicacionesgeologicas) · [Decreto Supremo 61, diseño sísmico de edificios](https://www.bcn.cl/leychile/navegar?idNorma=1034101).

Referencias nuevas: [CITSU SHOA](https://www.shoa.cl/php/citsu.php) · [CITSU Coquimbo–La Serena (metadatos y KMZ)](https://geoportal.cl/geoportal/catalog/35928/Capa%20Vectorial%20-%20Carta%20Inundaci%C3%B3n%20por%20Tsunami%20Coquimbo%20-%20La%20Serena) · [DGA mapas de amenaza de inundación](https://dga.mop.gob.cl/mapas-de-amenaza-de-inundacion/) · [DOH/SIALL](https://rest-sit.mop.gob.cl/arcgis/rest/services/DOH/SIALL/MapServer) · [SERNAGEOMIN, Peligros volcánicos](https://portalgeomin.sernageomin.cl/service/60de3ded818938000000).
