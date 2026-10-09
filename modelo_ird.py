"""Escalas MDSF (2025) para remoción en masa por FLUJOS y modelo de vulnerabilidad tsunami del proyecto.

El manual de escalas no define aquí la agregación final de los dos factores de amenaza.
Por ello se calculan ambos factores por separado y una combinación EXPLORATORIA,
que nunca debe presentarse como IRD oficial MDSF.
"""
from __future__ import annotations

from typing import Mapping

# Pesos internos de cada factor: Manual de escalas MDSF, septiembre 2025, pp. 6, 12.
PESOS_GENERACION = {"pendiente": 0.658, "escorrentia": 0.232, "fundacion": 0.110}
PESOS_ALCANCE = {"localizacion": 0.733, "taludes": 0.068, "intervencion": 0.199}

ESCALAS = {
    "pendiente": {"≥35°": 1.0, ">22° a <35°": 0.24, ">15° a ≤22°": 0.12, ">8° a ≤15°": 0.05, ">1° a ≤8°": 0.015},
    "escorrentia": {"≥0,30": 1.0, ">0,10 a <0,30": 0.43, "≤0,10": 0.13},
    "fundacion": {"E o F": 1.0, "D": 0.48, "C": 0.24, "B": 0.17, "A": 0.05},
    "localizacion": {"En cauce o fondo de valle": 1.0, "En abanico aluvial": 0.33, "Fuera del cauce y abanico": 0.11},
    "taludes": {"<50 m": 1.0, "50 a <150 m": 0.33, "≥150 m": 0.09},
    "intervencion": {"<40 m": 1.0, "40 a 99 m": 0.41, "100 a 299 m": 0.18, ">300 m": 0.08},
}

# Tabla 1, p. 10, coeficiente de escorrentía: columnas pendiente % >50,20-50,5-20,1-5,0-1.
TABLA_ESCORRENTIA = {
    "Sin vegetación": {"Impermeable": [.80,.75,.70,.65,.60], "Semipermeable": [.70,.65,.60,.55,.50], "Permeable": [.50,.45,.40,.35,.30]},
    "Cultivos": {"Impermeable": [.70,.65,.60,.55,.50], "Semipermeable": [.60,.55,.50,.45,.40], "Permeable": [.40,.35,.30,.25,.20]},
    "Pastos y vegetación ligera": {"Impermeable": [.65,.60,.55,.50,.45], "Semipermeable": [.55,.50,.45,.40,.35], "Permeable": [.35,.30,.25,.20,.15]},
    "Hierba": {"Impermeable": [.60,.55,.50,.45,.40], "Semipermeable": [.50,.45,.40,.35,.30], "Permeable": [.30,.25,.20,.15,.10]},
    "Bosque y vegetación densa": {"Impermeable": [.55,.50,.45,.40,.35], "Semipermeable": [.45,.40,.35,.30,.25], "Permeable": [.25,.20,.15,.10,.05]},
}

# Vulnerabilidad del modelo tsunami: materialidad 75%, antigüedad normativa 25%.
# Las categorías son valoraciones del proyecto, NO escalas de vulnerabilidad del manual MDSF.
MATERIALIDAD = {"Alta vulnerabilidad": 1.0, "Media vulnerabilidad": 0.53, "Baja vulnerabilidad": 0.22}
NORMATIVA = {"Anterior a 2010": 1.0, "Desde 2010": 0.22}


def puntaje_pendiente(grados: float) -> float | None:
    """Devuelve None en ≤1° o exactamente 22/35° ambiguos en la redacción del manual.

    35° sí está expresamente en el intervalo superior; 22° corresponde al medio.
    """
    if grados >= 35: return 1.0
    if grados > 22: return 0.24
    if grados > 15: return 0.12
    if grados > 8: return 0.05
    if grados > 1: return 0.015
    return None


def puntaje_escorrentia(coef: float) -> float:
    if not 0 <= coef <= 1: raise ValueError("Coeficiente de escorrentía fuera de [0,1]")
    return 1.0 if coef >= .30 else .43 if coef > .10 else .13


def coeficiente_escorrentia(cobertura: str, suelo: str, pendiente_pct: float) -> float:
    if pendiente_pct < 0: raise ValueError("Pendiente negativa")
    # Cortes operativos 0-1, >1-5, >5-20, >20-50, >50. Validar límites con formulador.
    idx = 0 if pendiente_pct > 50 else 1 if pendiente_pct > 20 else 2 if pendiente_pct > 5 else 3 if pendiente_pct > 1 else 4
    return TABLA_ESCORRENTIA[cobertura][suelo][idx]


def calcular_factores(selecciones: Mapping[str, float]) -> dict:
    faltantes = [k for k in ESCALAS if k not in selecciones or selecciones[k] is None]
    if faltantes: return {"completo": False, "faltantes": faltantes}
    for k, v in selecciones.items():
        if k in ESCALAS and v not in ESCALAS[k].values():
            raise ValueError(f"Valor inválido para {k}: {v}")
    generacion = sum(selecciones[k]*w for k,w in PESOS_GENERACION.items())
    alcance = sum(selecciones[k]*w for k,w in PESOS_ALCANCE.items())
    return {"completo": True, "condicionantes_generacion": round(generacion, 6), "area_alcance": round(alcance, 6)}


def vulnerabilidad_tsunami(materialidad: str, normativa: str) -> float:
    return .75*MATERIALIDAD[materialidad] + .25*NORMATIVA[normativa]


def indice_exploratorio(generacion: float, alcance: float, vulnerabilidad: float,
                        peso_generacion: float = .5, peso_amenaza: float = .667) -> dict:
    """Hipótesis EXPLORATORIA: agregación interna de amenaza 50/50; pesos del proyecto 66,7/33,3.

    No atribuir pesos de combinación a MDSF. El usuario puede ajustar los dos pesos.
    """
    if not 0 <= peso_generacion <= 1 or not 0 <= peso_amenaza <= 1:
        raise ValueError("Pesos fuera de [0,1]")
    amenaza = peso_generacion*generacion + (1-peso_generacion)*alcance
    ir = peso_amenaza*amenaza + (1-peso_amenaza)*vulnerabilidad
    return {"amenaza_exploratoria": round(amenaza, 6), "vulnerabilidad_proyecto": round(vulnerabilidad, 6),
            "indice_exploratorio": round(ir, 6), "no_oficial": True}
