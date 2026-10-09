# GeoRiskAI Sentinel — Remoción en masa por flujos

Aplicación Streamlit para seleccionar polígonos, analizar pendientes desde DEM GeoTIFF, aplicar las **escalas de amenaza** del *Manual de escalas para la estimación del IRD de amenaza por remoción en masa por flujos* (MDSF, septiembre de 2025) y utilizar la **valoración de vulnerabilidad propia del modelo tsunami** de GeoRiskAI Sentinel.

## Instalación en GitHub y Streamlit
1. Sube `app.py`, `modelo_ird.py`, `requirements.txt` y opcionalmente `test_modelo_ird.py` a la raíz de un repositorio GitHub.
2. En https://share.streamlit.io crea una aplicación con archivo principal `app.py`.
3. Dibuja un polígono o carga GeoJSON EPSG:4326. Para pendiente automática, carga un DEM GeoTIFF del sector o configura `DEM_PATH` apuntando a un archivo en el servidor.
4. Completa la cobertura y tipo de suelo para escorrentía; verifica suelo de fundación, localización, taludes e intervenciones.
5. Selecciona materialidad y antigüedad normativa del proyecto y descarga la ficha JSON.

## Metodología y límites
- Se aplican los pesos **internos** de condicionantes de generación (pendiente 65,8%; escorrentía 23,2%; fundación 11%) y área de alcance (localización 73,3%; taludes 6,8%; intervención 19,9%) establecidos en el manual MDSF.
- La vulnerabilidad propia del proyecto tsunami utiliza **materialidad 75% y normativa 25%** con valores 1 / 0,53 / 0,22 y 1 / 0,22, respectivamente. No corresponde a la vulnerabilidad oficial MDSF para flujos.
- **No se dispone en el manual aportado de la ecuación integral que combina ambos factores de amenaza, ni de su combinación con la vulnerabilidad del proyecto.** La integración final usa **66,7% amenaza y 33,3% vulnerabilidad** como ponderaciones definidas para GeoRiskAI Sentinel. La agregación interna de los dos factores de amenaza permanece configurable, con 50/50 provisional, y NO es oficial MDSF. Validar con la metodología complementaria y la fórmula final elegida antes de usar resultados para decisiones.
- No se descarga automáticamente Copernicus DEM ni Sentinel-2 en esta versión. La pendiente necesita DEM proporcionado por el usuario. La escorrentía requiere información de cobertura y suelo ingresada por el evaluador; otras variables requieren fuentes técnicas verificadas.
- La pendiente máxima derivada del DEM es sensible a resolución y bordes; revisar el procedimiento de celda de análisis del manual. El criterio ≤1° carece de categoría explícita en la escala transcrita y se pide valoración manual.
- Las capas de abanicos, cauces, taludes y geotecnia **no** se infieren de forma confiable solo de un mapa base.

## Pruebas
`python -m pytest test_modelo_ird.py` (requiere pytest instalado).
