# Datos y método — GeoRiskAI Relaves

## Lo que se sabe del ejemplo

El Consejo Minero identifica Las Tórtolas en Colina, operando desde 1992. SERNAGEOMIN mantiene un visor/catastro público de depósitos de relaves. La clasificación de consecuencias divulgada por el titular no es una probabilidad de falla.

## Lo que se puede observar con satélite

Sentinel-1 GRD está disponible históricamente desde 2014 y puede procesarse en ventanas de tiempo por área de interés. La app deja acceder a VV/VH usando OAuth de Copernicus Data Space. El radar permite examinar cambios de retrodispersión incluso con nubosidad, pero una diferencia no demuestra inundación ni anomalía de la presa. Para superficie de agua se requiere algoritmo validado localmente, referencia sin evento, control de geometría/orbita, lluvia, topografía y verdad terreno.

## Índice de exposición (futuro)

Construir una ficha independiente de “exposición y preparación”: población potencial aguas abajo, escuelas/centros críticos, tiempo/rutas de evacuación, cercanía a drenajes y servicios esenciales. No mezclar esta ficha con estabilidad física del depósito.

## Etiquetas para aprendizaje supervisado

Unidad sugerida: depósito × fecha/ventana temporal. Etiquetas: evento/condición confirmada, subtipo, fuente primaria, incertidumbre, alcance geográfico y fecha. No llamar “negativo” a un periodo sin registro. Dividir evaluación por depósito y tiempo; publicar sensibilidad, precisión, calibración y límites de dominio. Mientras no existan positivos/negativos verificados suficientes, mostrar reglas/indicadores y no presentar probabilidades ML.
