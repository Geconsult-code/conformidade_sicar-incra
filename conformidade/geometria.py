"""
geometria.py — utilitários geométricos da análise de conformidade SICAR × INCRA.

Este módulo concentra as operações de baixo nível que precisam ser IDÊNTICAS
às usadas na rotina validada no QGIS, para que os resultados do programa
reproduzam exatamente a classificação de referência (estado do Pará).

Pontos de fidelidade metodológica:

- Área GEODÉSICA calculada sobre o elipsoide GRS80, equivalente ao
  ``QgsDistanceArea`` com SIRGAS2000/GRS80. Isso torna a área independente
  da projeção e evita distorções ao processar estados de tamanhos e latitudes
  diferentes. O equivalente em Python é ``pyproj.Geod(ellps="GRS80")``.

- Geometrias são "achatadas" para 2D (remoção de coordenada Z) e validadas
  (``make_valid``) apenas em cópias de trabalho. A geometria ORIGINAL nunca é
  alterada nas saídas — só usamos as versões limpas para medir e comparar.
"""

from __future__ import annotations

from pyproj import Geod
from shapely import make_valid, force_2d
from shapely.geometry.base import BaseGeometry

# Elipsoide de referência. GRS80 é o elipsoide do SIRGAS2000 (EPSG:4674),
# datum oficial da cartografia brasileira e das bases SICAR/INCRA.
_GEOD = Geod(ellps="GRS80")

# CRS geográfico de trabalho. Todas as camadas são harmonizadas para cá.
CRS_TRABALHO = "EPSG:4674"  # SIRGAS 2000


def area_geodesica_m2(geom: BaseGeometry) -> float:
    """Área geodésica de ``geom`` em metros quadrados, sobre o elipsoide GRS80.

    A geometria deve estar em coordenadas geográficas (graus, EPSG:4674).
    Retorna 0.0 para geometrias vazias ou inválidas de medição.

    Equivale a ``QgsDistanceArea`` com elipsoide GRS80 no QGIS.
    """
    if geom is None or geom.is_empty:
        return 0.0
    try:
        area, _ = _GEOD.geometry_area_perimeter(geom)
        return abs(area)
    except Exception:
        return 0.0


def limpar_2d_valido(geom: BaseGeometry) -> BaseGeometry | None:
    """Devolve uma cópia 2D e topologicamente válida de ``geom``.

    Passos (espelham a função ``to2d_valid`` da rotina do QGIS):
      1. descarta se vazia/nula;
      2. remove a coordenada Z (força 2D);
      3. corrige geometria inválida com ``make_valid``.

    Retorna ``None`` se, após a limpeza, a geometria ficar vazia.
    Esta é uma cópia de TRABALHO — nunca substitui a geometria de saída.
    """
    if geom is None or geom.is_empty:
        return None
    g = force_2d(geom)
    if not g.is_valid:
        g = make_valid(g)
    if g is None or g.is_empty:
        return None
    return g


def fracao_area(inter_area: float, ref_area: float) -> float:
    """Razão segura ``inter_area / ref_area`` (0.0 se o denominador for <= 0)."""
    return inter_area / ref_area if ref_area > 0 else 0.0
