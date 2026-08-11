"""
teste_nucleo.py — testes dos módulos-núcleo com geometrias sintéticas.

Roda sem dados externos e sem pytest (basta ``python exemplos/teste_nucleo.py``),
mas também é compatível com ``pytest``. Cobre os cinco motivos, o filtro de
sobreposição e a subdivisão do contido_menor, com geometrias controladas cujo
resultado é conhecido.
"""

from __future__ import annotations

from shapely.geometry import Polygon

from conformidade.classificacao import ReferenciaINCRA, classificar_imovel
from conformidade.sobreposicao import calcular_sobreposicao
from conformidade.subdivisao import subdividir_contido_menor


def quad(x0, y0, x1, y1) -> Polygon:
    return Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)])


def test_motivos():
    ref = ReferenciaINCRA([quad(0, 0, 1, 1), quad(2, 2, 3, 3)])
    casos = {
        "contido_equivalente": quad(0.001, 0.001, 0.999, 0.999),
        "contido_menor": quad(0.1, 0.1, 0.3, 0.3),
        # deslocamento de 1% do lado: containment < 0,99 mas IoU >= 0,90
        "forma_similar": quad(2.01, 2.01, 3.01, 3.01),
        "forma_divergente": quad(0.5, 0.5, 2.2, 0.9),
        "sem_sobreposicao": quad(10, 10, 10.2, 10.2),
    }
    for esperado, g in casos.items():
        r = classificar_imovel(g, ref)
        assert r["motivo"] == esperado, f"{esperado}: obtido {r['motivo']}"


def test_sobreposicao():
    ids = ["A", "B", "C", "D"]
    geoms = [
        quad(0, 0, 1, 1),           # A grande -> representante
        quad(0.1, 0.1, 0.4, 0.4),   # B dentro de A -> redundante
        quad(0.2, 0.2, 0.5, 0.5),   # C dentro de A -> redundante
        quad(5, 5, 5.1, 5.1),       # D isolado -> representante
    ]
    res = calcular_sobreposicao(ids, geoms, limiar=0.70)
    assert res["A"].classe_espacial == "representante"
    assert res["B"].classe_espacial == "redundante_sobreposto"
    assert res["B"].pai_cod == "A"
    assert res["C"].classe_espacial == "redundante_sobreposto"
    assert res["D"].classe_espacial == "representante"


def test_subdivisao():
    ref_geoms = [quad(0, 0, 1, 1)]
    ids = ["G", "I", "S1", "S2"]
    geoms = [
        quad(0.02, 0.02, 0.98, 0.98),  # grande
        quad(0.05, 0.05, 0.15, 0.15),  # isolado
        quad(0.5, 0.5, 0.7, 0.7),      # sobreposto com S2
        quad(0.6, 0.6, 0.8, 0.8),      # sobreposto com S1
    ]
    sub = subdividir_contido_menor(ids, geoms, ref_geoms)
    assert sub["G"] == "contido_menor_grande"
    assert sub["I"] == "contido_menor_isolado"
    assert sub["S1"] == "contido_menor_sobreposto"
    assert sub["S2"] == "contido_menor_sobreposto"


def _run_all():
    fns = [test_motivos, test_sobreposicao, test_subdivisao]
    for fn in fns:
        fn()
        print(f"  OK  {fn.__name__}")
    print(f"\n{len(fns)} testes passaram.")


if __name__ == "__main__":
    _run_all()
