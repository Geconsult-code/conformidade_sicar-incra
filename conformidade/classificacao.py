"""
classificacao.py — classificação de coerência SICAR × INCRA (categoria ``motivo``).

Reproduz a metodologia validada no QGIS. Cada imóvel do SICAR é comparado à
referência fundiária do INCRA (SIGEF + SNCI) e recebe:

  - ``classe``  : "Coerente" ou "Incoerente"
  - ``motivo``  : um de cinco valores (ver abaixo)
  - métricas    : iou, delta_area, containment, hausdorff_rel, n_incra

Os cinco ``motivo`` possíveis:

  Coerente:
    - ``contido_equivalente`` : SICAR contido na referência E de tamanho
                                equivalente (a referência não é muito maior).
    - ``contido_menor``       : SICAR contido na referência, porém bem menor
                                (é um lote dentro de uma gleba maior).
    - ``forma_similar``       : não contido, mas forma e área batem
                                (IoU alto e diferença de área pequena).
  Incoerente:
    - ``forma_divergente``    : há sobreposição, mas forma/área divergem.
    - ``sem_sobreposicao``    : nenhuma sobreposição com a referência.

LÓGICA (ramos):

  Ramo A — containment >= CONTAIN_MIN (SICAR essencialmente dentro da união
           das referências que o intersectam):
             Coerente. Se |Δárea| <= DAREA_MAX  -> contido_equivalente
                       senão                    -> contido_menor

  Ramo B — caso contrário, reconstrói a referência R' com as parcelas do INCRA
           cuja MAIORIA da área (>= MAJORITY) cai dentro do SICAR (trata o
           caso 1:N, um SICAR cobrindo várias parcelas):
             se IoU >= IOU_MIN e |Δárea| <= DAREA_MAX -> Coerente/forma_similar
             senão                                    -> Incoerente/forma_divergente

  Ramo C — sem qualquer sobreposição -> Incoerente/sem_sobreposicao

Notas de fidelidade:
  - Todas as áreas são geodésicas (GRS80), independentes de projeção.
  - ``hausdorff_rel`` é apenas DIAGNÓSTICO — nunca entra no critério de
    classificação (é redundante com o IoU e sensível à escala).
  - A geometria original nunca é alterada; trabalhamos com cópias limpas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shapely import union_all
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from .geometria import area_geodesica_m2, limpar_2d_valido, fracao_area


@dataclass(frozen=True)
class Limiares:
    """Parâmetros da classificação. Os defaults são os validados no Pará."""
    iou_min: float = 0.90
    darea_max: float = 0.10
    contain_min: float = 0.99
    majority: float = 0.50


# Resultado da classificação de um imóvel: dicionário com chaves fixas.
CAMPOS_RESULTADO = (
    "classe", "motivo", "iou", "delta_area",
    "containment", "hausdorff_rel", "n_incra",
)


def _hausdorff_relativo(g: BaseGeometry, ref: BaseGeometry) -> float | None:
    """Distância de Hausdorff normalizada pela diagonal do bounding box.

    Apenas diagnóstico. Retorna ``None`` em caso de falha.
    """
    try:
        hd = g.hausdorff_distance(ref)
        minx, miny, maxx, maxy = g.bounds
        diag = ((maxx - minx) ** 2 + (maxy - miny) ** 2) ** 0.5
        return round(hd / diag, 4) if diag > 0 else None
    except Exception:
        return None


class ReferenciaINCRA:
    """Índice espacial da referência INCRA para classificação eficiente.

    Recebe uma lista de geometrias (já limpas, 2D, válidas) da referência
    (SIGEF + SNCI de uma dada natureza: pública ou privada) e pré-calcula
    áreas geodésicas e um índice STRtree para consultas rápidas.
    """

    def __init__(self, geometrias: list[BaseGeometry]):
        self.geoms: list[BaseGeometry] = []
        self.areas: list[float] = []
        for g in geometrias:
            gg = limpar_2d_valido(g)
            if gg is None:
                continue
            self.geoms.append(gg)
            self.areas.append(area_geodesica_m2(gg))
        self.tree = STRtree(self.geoms) if self.geoms else None

    def indices_intersectantes(self, geom: BaseGeometry) -> list[int]:
        """Índices das geometrias da referência que de fato intersectam ``geom``."""
        if self.tree is None:
            return []
        candidatos = self.tree.query(geom)  # filtro por bounding box
        return [int(i) for i in candidatos if geom.intersects(self.geoms[int(i)])]


def classificar_imovel(
    geom_sicar: BaseGeometry,
    ref: ReferenciaINCRA,
    lim: Limiares = Limiares(),
) -> dict[str, Any]:
    """Classifica um único imóvel do SICAR contra a referência INCRA.

    Retorna um dicionário com as chaves de ``CAMPOS_RESULTADO``.
    Não altera ``geom_sicar``.
    """
    r: dict[str, Any] = {
        "classe": "Incoerente", "motivo": "sem_sobreposicao",
        "iou": 0.0, "delta_area": None, "containment": 0.0,
        "hausdorff_rel": None, "n_incra": 0,
    }

    g = limpar_2d_valido(geom_sicar)
    if g is None:
        r["motivo"] = "geometria_invalida"
        return r
    a = area_geodesica_m2(g)
    if a <= 0:
        r["motivo"] = "area_nula"
        return r

    ov = ref.indices_intersectantes(g)
    r["n_incra"] = len(ov)
    if not ov:
        return r  # Ramo C: sem_sobreposicao

    # União das referências que intersectam o SICAR.
    R = union_all([ref.geoms[i] for i in ov])
    inter = g.intersection(R)
    a_inter = area_geodesica_m2(inter) if inter and not inter.is_empty else 0.0
    containment = fracao_area(a_inter, a)
    r["containment"] = round(containment, 4)

    # ---- Ramo A: SICAR essencialmente contido na referência --------------
    if containment >= lim.contain_min:
        a_R = area_geodesica_m2(R)
        uni = g.union(R)
        a_uni = area_geodesica_m2(uni) if uni and not uni.is_empty else a + a_R
        dar = abs(a - a_R) / a_R if a_R > 0 else None
        r["classe"] = "Coerente"
        r["motivo"] = (
            "contido_equivalente"
            if (dar is not None and dar <= lim.darea_max)
            else "contido_menor"
        )
        r["iou"] = round(a_inter / a_uni, 4) if a_uni > 0 else 0.0
        r["delta_area"] = round(dar, 4) if dar is not None else None
        r["hausdorff_rel"] = _hausdorff_relativo(g, R)
        return r

    # ---- Ramo B: reconstrói R' com parcelas majoritariamente dentro do SICAR
    parts = []
    for i in ov:
        it = g.intersection(ref.geoms[i])
        if it and not it.is_empty and ref.areas[i] > 0:
            if area_geodesica_m2(it) / ref.areas[i] >= lim.majority:
                parts.append(ref.geoms[i])
    Rp = union_all(parts) if parts else R

    ip = g.intersection(Rp)
    a_ip = area_geodesica_m2(ip) if ip and not ip.is_empty else 0.0
    up = g.union(Rp)
    a_up = area_geodesica_m2(up) if up and not up.is_empty else 0.0
    a_Rp = area_geodesica_m2(Rp)
    iou = a_ip / a_up if a_up > 0 else 0.0
    dar = abs(a - a_Rp) / a_Rp if a_Rp > 0 else None
    r["iou"] = round(iou, 4)
    r["delta_area"] = round(dar, 4) if dar is not None else None
    r["hausdorff_rel"] = _hausdorff_relativo(g, Rp)

    if iou >= lim.iou_min and dar is not None and dar <= lim.darea_max:
        r["classe"] = "Coerente"
        r["motivo"] = "forma_similar"
    else:
        r["classe"] = "Incoerente"
        r["motivo"] = "forma_divergente"
    return r
