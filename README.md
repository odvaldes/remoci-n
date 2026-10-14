# GeoRiskAI Sentinel — prototipo Streamlit

## Qué hace esta primera versión

- Recibe dirección, comuna, m² construidos y m² no construidos.
- Permite subir hasta cinco fotografías.
- Si está configurada una clave de OpenAI, solicita una estimación visual preliminar de nivel de daño/limpieza, superficie visible afectada, volumen de escombros y horas-hombre.
- Calcula un rango de presupuesto solo cuando se ingresan tarifas reales en el panel lateral.
- Incluye una solicitud separada para buscar orientación sobre una póliza vigente o cobertura para eventos futuros.
- Busca coincidencias solo en `insurance_partners.csv`; el archivo parte vacío para evitar mostrar empresas o pólizas no verificadas.
- Recibe consentimiento por separado para análisis de fotos, compartir datos con empresas y conservar fotos para mejorar el modelo.
- Guarda las solicitudes en Supabase si está configurado; localmente usa SQLite solo para pruebas.

El prototipo no contiene tarifas de empresas verificadas ni una base de proveedores. La asignación a empresas queda pendiente de revisión manual. Las estimaciones fotográficas son experimentales y deben contrastarse con mediciones y trabajos reales antes de usarlas como cotización definitiva. El módulo de daño entrega un nivel y superficie visual afectada; todavía no calcula pérdida económica en pesos ni determina cobertura de una póliza.

## Ejecutar en el computador

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

En Windows, activa el entorno con `.venv\\Scripts\\activate`.

Para probar solo la interfaz no necesitas OpenAI ni Supabase. Sin OpenAI, no se calcula el resultado visual. Sin Supabase, la base SQLite local sirve para pruebas, pero no es persistente al desplegar en Streamlit Community Cloud.

## Activar análisis de fotografías

Configura `OPENAI_API_KEY` en `.streamlit/secrets.toml` local o en Secrets de Streamlit Cloud. Las llamadas a la API pueden generar cobros según la cuenta y el uso. La app solicita consentimiento antes de enviar las fotos.

## Guardar solicitudes en Supabase

1. Crea un proyecto Supabase.
2. Ejecuta `schema_supabase.sql` en el SQL Editor.
3. Copia `SUPABASE_URL` y `SUPABASE_ANON_KEY` desde el proyecto a Secrets.
4. No publiques `secrets.toml` ni claves privadas en el repositorio.

La tabla tiene inserción anónima para este piloto y no permite leer las solicitudes desde la app. Administra y revisa los registros desde Supabase. Antes de abrir el piloto al público, agrega controles contra spam, autenticación administrativa y una política de privacidad adecuada.

## Cargar intermediarios y pólizas para el match

Completa `insurance_partners.csv` solo después de revisar los antecedentes del corredor, liquidador o aseguradora y las condiciones de la póliza. `communes` y `risks` aceptan varios valores separados por `|`; usa `*` en `communes` para cobertura nacional. Marca `verified=true` y `active=true` solo tras revisar la vigencia en la CMF. El match filtra por comuna, amenaza y tipo de solicitud. No es una validación automática de cobertura.

## Despliegue en Streamlit Community Cloud

Sube `app.py`, `requirements.txt` y `schema_supabase.sql` a un repositorio GitHub. En Streamlit Community Cloud selecciona ese repositorio y como archivo principal `app.py`. Después configura las claves en la sección Secrets de la app.
