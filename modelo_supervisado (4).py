"""Entrenamiento experimental con separación por depósito para evitar fuga espacial."""
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import roc_auc_score, recall_score, precision_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import make_pipeline

FEATURES = ["lluvia_72h_mm", "agua_proxy", "cambio_retrodispersion", "personas_aguas_abajo", "distancia_cauce_m"]

def entrenar_por_deposito(df: pd.DataFrame) -> dict:
    required = set(FEATURES + ["evento_confirmado", "grupo_deposito"])
    missing = sorted(required - set(df.columns))
    if missing:
        return {"ok": False, "message": "Faltan columnas: " + ", ".join(missing)}
    d = df.dropna(subset=["evento_confirmado", "grupo_deposito"]).copy()
    d["evento_confirmado"] = pd.to_numeric(d["evento_confirmado"], errors="coerce")
    d = d[d.evento_confirmado.isin([0, 1])]
    if d.evento_confirmado.nunique() < 2:
        return {"ok": False, "message": "Se requieren etiquetas verificadas de ambas clases (evento y no evento); no uses ausencia de reporte como clase 0."}
    if d.grupo_deposito.nunique() < 3:
        return {"ok": False, "message": "Se requieren al menos 3 depósitos etiquetados para separar entrenamiento y evaluación por sitio."}
    # Busca una partición de grupos con ambas clases en train y test.
    splitter = GroupShuffleSplit(n_splits=50, test_size=0.33, random_state=17)
    split = None
    y = d.evento_confirmado.astype(int)
    for tr, te in splitter.split(d[FEATURES], y, groups=d.grupo_deposito):
        if y.iloc[tr].nunique() == 2 and y.iloc[te].nunique() == 2:
            split = tr, te; break
    if split is None:
        return {"ok": False, "message": "No se encontró una partición por depósito con ambas clases en train/test. Hace falta más diversidad de sitios/eventos."}
    tr, te = split
    model = make_pipeline(SimpleImputer(strategy="median"), RandomForestClassifier(n_estimators=300, class_weight="balanced", min_samples_leaf=2, random_state=17))
    model.fit(d.iloc[tr][FEATURES], y.iloc[tr])
    p = model.predict_proba(d.iloc[te][FEATURES])[:, 1]
    pred = (p >= 0.5).astype(int)
    return {"ok": True, "n_sites": int(d.iloc[te].grupo_deposito.nunique()), "auc": float(roc_auc_score(y.iloc[te], p)), "recall": float(recall_score(y.iloc[te], pred, zero_division=0)), "precision": float(precision_score(y.iloc[te], pred, zero_division=0)), "model": model}
