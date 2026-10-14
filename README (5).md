# GeoRiskAI Relaves — prototipo Streamlit

MVP para explorar los polígonos nacionales de depósitos de relaves SERNAGEOMIN, cartografía censal INE 2024 urbana y rural cercana, red hidrográfica DGA/MOP (incluye cauces y quebradas), cuencas BNA atribuidas a DGA y contexto del Balance Hídrico Nacional, señales históricas de Sentinel-1, exposición de comunidades y una ruta de entrenamiento supervisado. Caso inicial: Las Tórtolas, Colina.

## Ejecutar

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
streamlit run app.py
```

## Habilitar consulta histórica Copernicus
1. Crear cuenta y OAuth client en Copernicus Data Space Ecosystem.
2. Crear `.streamlit/secrets.toml` a partir de `.streamlit_secrets.example.toml`.
3. Ejecutar la app y consultar un intervalo temporal.

El prototipo muestra el polígono de todos los relaves del servicio areal de SERNAGEOMIN; al seleccionar un sitio carga manzanas urbanas y entidades rurales censales del INE 2024 en el radio escogido. El mapa abre con imagen satelital Esri y permite alternar a calles desde el selector de capas. Las manzanas urbanas y entidades rurales censales (que pueden incluir aldeas/localidades pequeñas) se distinguen por color y borde discontinuo. El prototipo consulta cauces DGA/MOP, identifica la cuenca BNA del depósito y muestra vínculos al Balance Hídrico DGA (período histórico 1985–2015) y a estadísticas de estaciones hidrométricas. El balance nacional sirve como contexto de disponibilidad y flujos de largo plazo; no reemplaza observaciones de crecida ni da dirección local del flujo. El prototipo realiza además una prueba topológica preliminar para encontrar continuidad cartográfica entre el polígono del relave y polígonos censales poblados. El prototipo consulta hasta ocho ventanas históricas distribuidas en el periodo seleccionado y permite descargar VV/VH como GeoTIFF. Las bandas no se convierten en nivel de inundación ni probabilidad de falla. Para operacionalizar debe añadirse calibración radiométrica/geométrica, máscara de agua validada, mosaicos consistentes, DEM y validación en terreno.

## Límites que deben mantenerse visibles

- No estima probabilidad de colapso ni sustituye estudios de estabilidad, mapas oficiales de inundación, planes de emergencia o decisiones de autoridad.
- El radar observa cambios superficiales; puede confundir agua, humedad, obras, vegetación y geometría.
- La geometría del catastro areal es una referencia de SERNAGEOMIN, no una delimitación jurídica ni una evaluación de estabilidad. El servicio consultado se denomina CDR_CHILE_AREAL_2025 y declara actualización a octubre de 2025.
- Las manzanas urbanas y entidades rurales provienen de cartografía censal INE 2024; no representan necesariamente ocupación actual parcela a parcela ni sustituyen validación municipal/terreno. El chequeo de continuidad con la red de cauces DGA/MOP es aproximado: no determina sentido del flujo, caudal, inundación ni alcance de una eventual falla. Un resultado negativo tampoco descarta quebradas menores ausentes de la cartografía.
- La cobertura depende de que los servicios ArcGIS estén disponibles y de la conectividad de Streamlit.
- La capa DGA/MOP de cauces está integrada para screening. Falta validar localidades y ocupación en terreno, añadir un modelo de elevación para inferir dirección de flujo y cuencas, y modelar escenarios hidráulicos de rotura.
- Un modelo supervisado sólo debe entrenarse con eventos y no eventos verificados, fuentes citables y evaluación por depósito separado (sin fuga espacial/temporal).

## Siguiente etapa de datos

1. Servicio/catastro vigente de SERNAGEOMIN y polígono areal del depósito.
2. Comunidades y población: cartografía Censo INE 2024, municipalidad y localidades; integrar población sólo en agregados y resguardar datos personales.
3. Sentinel-1 histórico y Sentinel-2 óptico; revisar cuerpos de agua contra lluvia, inspecciones y registros de operación.
4. Modelo digital de elevación, dirección de flujo, drenaje y escenarios hidráulicos elaborados por especialistas; verificar la continuidad preliminar de cauces con visitas de terreno. Integrar valores numéricos del Balance Hídrico DGA por cuenca requiere vincular las tablas digitales del estudio con los códigos BNA/DARH y documentar su período y metodología; el visor actual identifica la cuenca y enlaza la fuente oficial, pero no inventa esos valores.
5. Etiquetas de incidentes: registros de autoridad, monitoreo, inspección y ejercicios; separar categorías (incidente, anomalía, inundación observada, falla).

## Financiamiento sugerido

Piloto patrocinado por la minera titular con contrato anual por sitio, incluyendo acceso público sin costo para comunidades; convenios universitarios/municipales y fondos públicos para validación independiente. La gobernanza debe impedir que el patrocinador altere puntajes o suprima alertas, y definir publicación, privacidad, auditoría y respuesta a incidentes.
