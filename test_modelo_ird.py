from modelo_ird import *

def test_escalas():
    assert puntaje_pendiente(35) == 1.0
    assert puntaje_pendiente(22) == .12
    assert puntaje_pendiente(10) == .05
    assert puntaje_pendiente(.5) is None
    assert puntaje_escorrentia(.3) == 1.0
    assert coeficiente_escorrentia('Sin vegetación','Impermeable',55) == .8

def test_factores():
    s = {k:max(v.values()) for k,v in ESCALAS.items()}
    x=calcular_factores(s)
    assert x['completo']
    assert x['condicionantes_generacion'] == 1.0
    assert x['area_alcance'] == 1.0
    assert calcular_factores({'pendiente':1.0})['completo'] is False

def test_vulnerabilidad():
    assert vulnerabilidad_tsunami('Alta vulnerabilidad','Anterior a 2010') == 1.0
    assert round(vulnerabilidad_tsunami('Media vulnerabilidad','Desde 2010'),4) == .4525


def test_ponderaciones_proyecto():
    r = indice_exploratorio(1.0, 1.0, 0.0)
    assert r["indice_exploratorio"] == 0.667
    r2 = indice_exploratorio(0.0, 0.0, 1.0)
    assert r2["indice_exploratorio"] == 0.333
