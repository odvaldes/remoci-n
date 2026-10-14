# GeoRiskAI Relaves — prototipo Streamlit

MVP para explorar depósitos de relaves, señales históricas de Sentinel-1, exposición de comunidades y una ruta de entrenamiento supervisado. Caso demo referencial: Las Tórtolas, Colina.

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

El prototipo divide el periodo en intervalos de seis meses y permite descargar VV/VH como GeoTIFF. Las bandas no se convierten en nivel de inundación ni probabilidad de falla. Para operacionalizar debe añadirse calibración radiométrica/geométrica, máscara de agua validada, mosaicos consistentes, DEM y validación en terreno.

## Límites que deben mantenerse visibles

- No estima probabilidad de colapso ni sustituye estudios de estabilidad, mapas oficiales de inundación, planes de emergencia o decisiones de autoridad.
- El radar observa cambios superficiales; puede confundir agua, humedad, obras, vegetación y geometría.
- El punto de Las Tórtolas es aproximado para demo. Reemplazarlo por geometría oficial del catastro vigente.
- Falta integrar un catastro de población/comunidades validado, hidrografía, elevación y escenarios hidráulicos de rotura.
- Un modelo supervisado sólo debe entrenarse con eventos y no eventos verificados, fuentes citables y evaluación por depósito separado (sin fuga espacial/temporal).

## Siguiente etapa de datos

1. Servicio/catastro vigente de SERNAGEOMIN y polígono del depósito.
2. Comunidades y población: INE/Censo, municipalidad, localidades; resguardar datos personales.
3. Sentinel-1 histórico y Sentinel-2 óptico; revisar cuerpos de agua contra lluvia, inspecciones y registros de operación.
4. Modelo digital de elevación, drenaje y escenarios hidráulicos elaborados por especialistas.
5. Etiquetas de incidentes: registros de autoridad, monitoreo, inspección y ejercicios; separar categorías (incidente, anomalía, inundación observada, falla).

## Financiamiento sugerido

Piloto patrocinado por la minera titular con contrato anual por sitio, incluyendo acceso público sin costo para comunidades; convenios universitarios/municipales y fondos públicos para validación independiente. La gobernanza debe impedir que el patrocinador altere puntajes o suprima alertas, y definir publicación, privacidad, auditoría y respuesta a incidentes.
