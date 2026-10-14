"""GeoRiskAI Sentinel – MVP Streamlit.

Prototype for collecting property data/photos, requesting a preliminary visual
assessment, and calculating a transparent quote range from configured tariffs.
The image-based volume and work-hour estimates are experimental and need field
validation before being used for real commercial quotes.
"""

from __future__ import annotations

import base64
import csv
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

import streamlit as st

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None

try:
    from supabase import create_client
except ImportError:  # pragma: no cover
    create_client = None


APP_DIR = Path(__file__).resolve().parent
LOCAL_DB = APP_DIR / "georiskai_local.sqlite3"
PHOTO_BUCKET = "georiskai-photos"
INSURANCE_PARTNERS_FILE = APP_DIR / "insurance_partners.csv"


def get_setting(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value:
        return value
    try:
        return str(st.secrets.get(name, default))
    except Exception:
        return default


def numeric_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
        return number if number >= 0 else None
    except (TypeError, ValueError):
        return None


def prepare_photo(uploaded_file: Any) -> tuple[bytes, str]:
    """Resize and normalize a photo so it can be sent to a vision model."""
    raw = uploaded_file.getvalue()
    if Image is None:
        return raw, uploaded_file.type or "image/jpeg"
    image = Image.open(BytesIO(raw)).convert("RGB")
    image.thumbnail((1800, 1800))
    output = BytesIO()
    image.save(output, format="JPEG", quality=82, optimize=True)
    return output.getvalue(), "image/jpeg"


def analyze_photos(
    photos: list[tuple[bytes, str]], built_m2: float, unbuilt_m2: float
) -> dict[str, Any]:
    api_key = get_setting("OPENAI_API_KEY")
    model = get_setting("OPENAI_VISION_MODEL", "gpt-4.1-mini")
    if not api_key or OpenAI is None:
        raise RuntimeError(
            "Falta OPENAI_API_KEY. Configúrala en Streamlit Secrets para activar "
            "el análisis de fotos. Sin esa clave, la app no inventa resultados."
        )

    prompt = f"""Analiza las fotografías de una propiedad afectada por un evento.
Superficie construida informada: {built_m2} m².
Superficie no construida informada: {unbuilt_m2} m².

Devuelve exclusivamente un objeto JSON válido con estas claves:
cleaning_level: una de "leve", "moderado", "alto", "crítico" o "indeterminado";
damage_level: una de "leve", "moderado", "alto", "crítico" o "indeterminado";
damage_notes: descripción breve de daños visibles, sin diagnosticar estructura;
debris_volume_m3_min y debris_volume_m3_max: números o null;
person_hours_min y person_hours_max: números o null;
affected_built_area_m2 y affected_unbuilt_area_m2: números o null;
recommended_services: lista usando solo "retiro", "limpieza", "reparaciones", "vidrios";
confidence: "baja", "media" o "alta";
visual_notes: texto breve en español.

Entrega rangos preliminares, no una tasación ni una cotización definitiva. No
supongas lo que queda fuera de las fotos. Usa las superficies informadas como
referencia de escala, pero no las trates como área afectada. Si la perspectiva,
ocultamiento o falta de escala impiden estimar volumen u horas, devuelve null.
No infieras daños estructurales ni riesgos de salud no claramente visibles."""

    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for image_bytes, mime in photos:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime};base64,{encoded}",
                    "detail": "high",
                },
            }
        )

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "Eres un estimador visual preliminar. Responde solo JSON.",
            },
            {"role": "user", "content": content},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    raw = response.choices[0].message.content or "{}"
    result = json.loads(raw)

    for field in (
        "debris_volume_m3_min",
        "debris_volume_m3_max",
        "person_hours_min",
        "person_hours_max",
        "affected_built_area_m2",
        "affected_unbuilt_area_m2",
    ):
        result[field] = numeric_or_none(result.get(field))
    result.setdefault("cleaning_level", "indeterminado")
    result.setdefault("damage_level", "indeterminado")
    result.setdefault("damage_notes", "")
    result.setdefault("recommended_services", [])
    result.setdefault("confidence", "baja")
    result.setdefault("visual_notes", "")
    return result


def quote_range(
    assessment: dict[str, Any],
    hourly_rate: float,
    removal_rate_m3: float,
    transport_fixed: float,
    equipment_fixed: float,
    crew_size: int,
    hours_per_shift: float,
) -> tuple[float, float] | None:
    h_min = assessment.get("person_hours_min")
    h_max = assessment.get("person_hours_max")
    v_min = assessment.get("debris_volume_m3_min")
    v_max = assessment.get("debris_volume_m3_max")
    if h_min is None or h_max is None or v_min is None or v_max is None:
        return None
    if hourly_rate <= 0 and removal_rate_m3 <= 0:
        return None
    low = h_min * hourly_rate + v_min * removal_rate_m3
    high = h_max * hourly_rate + v_max * removal_rate_m3
    low += transport_fixed + equipment_fixed
    high += transport_fixed + equipment_fixed
    return low, high


def save_locally(record: dict[str, Any]) -> None:
    """Local fallback for development. Streamlit Cloud disk is not durable."""
    with sqlite3.connect(LOCAL_DB) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS requests "
            "(id TEXT PRIMARY KEY, created_at TEXT, payload TEXT)"
        )
        connection.execute(
            "INSERT INTO requests (id, created_at, payload) VALUES (?, ?, ?)",
            (record["id"], record["created_at"], json.dumps(record, ensure_ascii=False)),
        )
        connection.commit()


def save_supabase(record: dict[str, Any], photos: list[tuple[bytes, str]]) -> None:
    url = get_setting("SUPABASE_URL")
    key = get_setting("SUPABASE_ANON_KEY")
    if not url or not key or create_client is None:
        raise RuntimeError("Supabase no está configurado.")

    client = create_client(url, key)
    if record.get("consent_training_photos") and photos:
        stored_paths = []
        for index, (photo_bytes, mime) in enumerate(photos, start=1):
            path = f"{record['id']}/{index}.jpg"
            client.storage.from_(PHOTO_BUCKET).upload(
                path,
                photo_bytes,
                {"content-type": mime, "upsert": "false"},
            )
            stored_paths.append(path)
        record["photo_paths"] = stored_paths
    client.table("georiskai_requests").insert(record).execute()


def load_insurance_partners() -> list[dict[str, str]]:
    """Load only partners and products manually verified by the app operator."""
    if not INSURANCE_PARTNERS_FILE.exists():
        return []
    with INSURANCE_PARTNERS_FILE.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def match_insurance_partners(
    comuna: str, risks: list[str], claim_support: bool
) -> list[dict[str, str]]:
    matches = []
    for partner in load_insurance_partners():
        truthy = lambda key: partner.get(key, "").strip().lower() in {"1", "true", "si", "sí", "yes"}
        if not truthy("active") or not truthy("verified"):
            continue
        if not partner.get("verified_on") or not partner.get("cmf_registration"):
            continue
        if claim_support and not truthy("claim_support"):
            continue
        if not claim_support and not truthy("future_cover"):
            continue
        areas = [x.strip().casefold() for x in partner.get("communes", "").split("|") if x.strip()]
        if "*" not in areas and comuna.strip().casefold() not in areas:
            continue
        covered_risks = [x.strip().casefold() for x in partner.get("risks", "").split("|") if x.strip()]
        if not claim_support and not any(risk.casefold() in covered_risks for risk in risks):
            continue
        if not partner.get("contact_url") and not partner.get("contact_email"):
            continue
        matches.append(partner)
    return matches


def save_insurance_request(record: dict[str, Any]) -> None:
    url = get_setting("SUPABASE_URL")
    key = get_setting("SUPABASE_ANON_KEY")
    if url and key and create_client is not None:
        client = create_client(url, key)
        client.table("georiskai_insurance_requests").insert(record).execute()
    else:
        save_locally(record)


st.set_page_config(page_title="GeoRiskAI Sentinel", page_icon="🌊", layout="centered")
st.title("GeoRiskAI Sentinel")
st.caption("Evaluación preliminar y solicitud de servicios para inmuebles afectados")
st.info(
    "Prototipo de validación. El análisis fotográfico y los presupuestos son "
    "referenciales; requieren contraste con empresas y mediciones reales."
)

with st.sidebar:
    st.header("Parámetros de presupuesto")
    st.caption("Ingresa tarifas reales de referencia. En cero, el total no se calcula.")
    rate_hour = st.number_input("Tarifa por hora-hombre (CLP)", min_value=0, step=1000)
    rate_m3 = st.number_input("Retiro/disposición por m³ (CLP)", min_value=0, step=5000)
    transport = st.number_input("Transporte fijo (CLP)", min_value=0, step=5000)
    equipment = st.number_input("Equipos/materiales (CLP)", min_value=0, step=5000)
    crew = st.number_input("Personas por cuadrilla", min_value=1, max_value=20, value=2)
    shift_hours = st.number_input("Horas por jornada-equipo", min_value=1.0, max_value=16.0, value=8.0)
    st.caption("La jornada-equipo es una unidad comercial configurable.")

st.subheader("1. Datos del inmueble")
with st.form("assessment_form", clear_on_submit=False):
    c1, c2 = st.columns(2)
    with c1:
        address = st.text_input("Dirección o ubicación", placeholder="Calle, número, comuna")
        comuna = st.text_input("Comuna", placeholder="Ej.: Coquimbo")
        built_m2 = st.number_input("Superficie construida (m²)", min_value=0.0, step=1.0)
    with c2:
        event_type = st.selectbox(
            "Evento", ["Tsunami/maremoto", "Remoción en masa", "Inundación", "Incendio", "Otro"]
        )
        unbuilt_m2 = st.number_input("Superficie no construida (m²)", min_value=0.0, step=1.0)
        contact_name = st.text_input("Nombre", placeholder="Opcional")

    email = st.text_input("Correo para recibir respuesta", placeholder="Opcional")
    phone = st.text_input("Teléfono", placeholder="Opcional")
    photos_upload = st.file_uploader(
        "Fotos del inmueble y de las zonas afectadas (hasta 5)",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
    )
    selected_services = st.multiselect(
        "Servicios que podrían interesarte",
        ["Retiro de escombros", "Limpieza", "Reparaciones", "Cambio de vidrios"],
    )

    st.markdown("**Permisos y uso de datos**")
    consent_ai = st.checkbox(
        "Autorizo enviar las fotos a un servicio de IA para generar una estimación preliminar.",
        value=False,
    )
    consent_provider = st.checkbox(
        "Autorizo compartir mis datos de contacto y ubicación con empresas para solicitar cotizaciones.",
        value=False,
    )
    consent_training = st.checkbox(
        "Autorizo conservar mis fotos y datos anonimizados para mejorar el modelo.",
        value=False,
    )
    submitted = st.form_submit_button("Analizar y generar presupuesto", type="primary")

if submitted:
    if not address or not comuna:
        st.error("Ingresa una dirección y comuna para registrar la solicitud.")
        st.stop()
    if len(photos_upload or []) > 5:
        st.error("Puedes cargar hasta cinco fotos.")
        st.stop()
    if not photos_upload:
        st.error("Carga al menos una foto para solicitar el análisis visual.")
        st.stop()
    if not consent_ai:
        st.error("Para analizar las imágenes debes autorizar su envío al servicio de IA.")
        st.stop()

    normalized_photos = [prepare_photo(photo) for photo in photos_upload]
    with st.spinner("Analizando las imágenes. La estimación puede variar según el ángulo y la visibilidad..."):
        try:
            assessment = analyze_photos(normalized_photos, built_m2, unbuilt_m2)
            status = "estimacion_visual_generada"
        except Exception as exc:
            assessment = None
            status = "pendiente_analisis"
            st.error(f"No se pudo completar el análisis: {exc}")

    record_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    budget = (
        quote_range(assessment, rate_hour, rate_m3, transport, equipment, int(crew), shift_hours)
        if assessment
        else None
    )
    record: dict[str, Any] = {
        "id": record_id,
        "created_at": now,
        "address": address,
        "comuna": comuna,
        "event_type": event_type,
        "built_m2": built_m2,
        "unbuilt_m2": unbuilt_m2,
        "contact_name": contact_name or None,
        "email": email or None,
        "phone": phone or None,
        "requested_services": selected_services,
        "consent_ai": consent_ai,
        "consent_provider_sharing": consent_provider,
        "consent_training_photos": consent_training,
        "analysis_status": status,
        "assessment": assessment,
        "budget_min_clp": budget[0] if budget else None,
        "budget_max_clp": budget[1] if budget else None,
        "provider_match_status": "pendiente_revision_manual",
    }

    try:
        if get_setting("SUPABASE_URL") and get_setting("SUPABASE_ANON_KEY"):
            save_supabase(record, normalized_photos)
            storage_note = "Solicitud guardada en Supabase."
        else:
            save_locally(record)
            storage_note = "Solicitud guardada localmente."
        st.session_state["last_record"] = record
        st.success(storage_note)
    except Exception as exc:
        st.session_state["last_record"] = record
        st.warning(f"Resultado generado, pero no se pudo guardar: {exc}")

    if assessment:
        st.divider()
        st.subheader("2. Resultado preliminar")
        st.write(f"**Nivel de limpieza:** {assessment.get('cleaning_level', 'indeterminado').capitalize()}")
        st.write(f"**Nivel de daño físico visible:** {assessment.get('damage_level', 'indeterminado').capitalize()}")
        st.write(f"**Confianza visual:** {assessment.get('confidence', 'baja').capitalize()}")
        vmin, vmax = assessment.get("debris_volume_m3_min"), assessment.get("debris_volume_m3_max")
        hmin, hmax = assessment.get("person_hours_min"), assessment.get("person_hours_max")
        if vmin is not None and vmax is not None:
            st.metric("Volumen estimado de escombros", f"{vmin:g}–{vmax:g} m³")
        else:
            st.warning("Las fotos no permiten estimar un volumen con confianza suficiente.")
        if hmin is not None and hmax is not None:
            jmin = hmin / (int(crew) * shift_hours)
            jmax = hmax / (int(crew) * shift_hours)
            st.write(f"**Trabajo estimado:** {hmin:g}–{hmax:g} horas-hombre")
            st.write(f"**Jornadas-equipo estimadas:** {jmin:.1f}–{jmax:.1f} (cuadrilla de {int(crew)})")
        if budget:
            st.metric("Presupuesto referencial", f"${budget[0]:,.0f}–${budget[1]:,.0f} CLP")
        else:
            st.info("Ingresa tarifas de referencia en el panel lateral para calcular un rango de presupuesto.")
        st.write(assessment.get("visual_notes", ""))
        if assessment.get("damage_notes"):
            st.write("**Daños visibles:** " + assessment["damage_notes"])
        services = assessment.get("recommended_services", [])
        if services:
            st.write("**Servicios sugeridos por las fotos:** " + ", ".join(services))
        st.caption(
            "Estimación automática experimental; no constituye tasación, diagnóstico estructural "
            "ni precio definitivo. Una empresa debe confirmar alcance y precio."
        )
        if consent_provider:
            st.info("La solicitud queda disponible para revisión y asignación manual a empresas verificadas.")
        else:
            st.info("No compartiremos tus datos con empresas; puedes solicitar cotizaciones más adelante.")

st.divider()
st.caption(
    "Para guardar solicitudes de manera persistente en Streamlit Cloud, configura Supabase. "
    "Sin Supabase, el prototipo usa una base local temporal."
)

st.divider()
st.header("3. Match de seguros")
st.write(
    "Usa el resultado territorial de GeoRiskAI para encontrar orientación con un "
    "corredor, aseguradora o liquidador que tenga cobertura o atención pertinente."
)
insurance_intent = st.radio(
    "¿Qué necesitas?",
    [
        "Ya ocurrió un evento: orientación sobre un seguro vigente",
        "Quiero buscar cobertura para eventos futuros",
    ],
    horizontal=False,
    key="insurance_intent",
)
previous_property = st.session_state.get("last_record", {})
previous_event = previous_property.get("event_type", "")
hazard_options = ["Tsunami/maremoto", "Remoción en masa", "Inundación", "Incendio", "Sismo"]
hazard_default = [previous_event] if previous_event in hazard_options else []

with st.form("insurance_form", clear_on_submit=False):
    comuna_ins = st.text_input(
        "Comuna del inmueble", value=previous_property.get("comuna", ""), key="insurance_comuna"
    )
    risks_ins = st.multiselect(
        "Amenazas de interés",
        hazard_options,
        default=hazard_default,
        key="insurance_risks",
    )
    if insurance_intent.startswith("Ya ocurrió"):
        active_policy = st.selectbox(
            "¿Tienes una póliza vigente para este inmueble?",
            ["Sí", "No", "No estoy segura"],
            key="active_policy",
        )
    else:
        active_policy = "No aplica"
    insurance_name = st.text_input("Nombre", key="insurance_name")
    insurance_email = st.text_input("Correo", key="insurance_email")
    insurance_phone = st.text_input("Teléfono", key="insurance_phone")
    consent_insurance_contact = st.checkbox(
        "Autorizo guardar mis datos de contacto para gestionar esta solicitud de orientación.",
        key="consent_insurance_contact",
    )
    insurance_submitted = st.form_submit_button("Buscar coincidencias de seguro", type="primary")

if insurance_submitted:
    if not comuna_ins:
        st.error("Indica la comuna para buscar coincidencias.")
        st.stop()
    claim_support = insurance_intent.startswith("Ya ocurrió")
    if claim_support and active_policy == "No":
        st.warning(
            "Una póliza contratada después del evento no cubre ese daño ya ocurrido. "
            "Puedes cambiar a la opción de cobertura para eventos futuros."
        )
        insurance_matches: list[dict[str, str]] = []
    else:
        insurance_matches = match_insurance_partners(comuna_ins, risks_ins, claim_support)

    insurance_record = {
        "id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "comuna": comuna_ins,
        "risks": risks_ins,
        "purpose": "claim_support" if claim_support else "future_coverage",
        "active_policy_status": active_policy,
        "contact_name": insurance_name if consent_insurance_contact else None,
        "email": insurance_email if consent_insurance_contact else None,
        "phone": insurance_phone if consent_insurance_contact else None,
        "consent_contact_sharing": consent_insurance_contact,
        "matched_partner_names": [p.get("partner_name", "") for p in insurance_matches],
        "match_status": "matches_found" if insurance_matches else "no_verified_match_loaded",
    }
    try:
        save_insurance_request(insurance_record)
        st.success("Solicitud de match registrada.")
    except Exception as exc:
        st.warning(f"No se pudo guardar la solicitud: {exc}")

    if insurance_matches:
        st.subheader("Coincidencias disponibles")
        for partner in insurance_matches:
            with st.container(border=True):
                st.markdown(f"**{partner.get('partner_name', 'Intermediario')}** · {partner.get('partner_type', '')}")
                if partner.get("product_name"):
                    st.write("Producto/cobertura informada: " + partner["product_name"])
                if partner.get("policy_code"):
                    st.write("Código de póliza CMF: " + partner["policy_code"])
                if partner.get("verified_on"):
                    st.caption("Registro revisado: " + partner["verified_on"])
                if partner.get("policy_url"):
                    st.markdown(f"[Revisar condiciones de la póliza]({partner['policy_url']})")
                if partner.get("contact_url"):
                    st.link_button("Contactar", partner["contact_url"])
                elif partner.get("contact_email"):
                    st.write("Contacto: " + partner["contact_email"])
    else:
        st.info(
            "Aún no hay empresas o pólizas verificadas cargadas para esta comuna y amenaza. "
            "No mostraremos productos inventados."
        )

    if claim_support:
        st.markdown(
            "Para revisar pólizas que ya tienes, puedes usar el "
            "[Sistema de Consultas de Seguros de la CMF](https://www.cmfchile.cl/portal/principal/623/w4-propertyvalue-49613.html). "
            "GeoRiskAI no solicita ni almacena tu ClaveÚnica."
        )
    st.caption(
        "El match orienta hacia intermediarios o productos cargados y verificados; "
        "no confirma cobertura ni reemplaza la asesoría del corredor, la evaluación "
        "de la aseguradora o la liquidación del siniestro."
    )
