"""
subdivisao.py — subdivisão do ``motivo`` = ``contido_menor`` em três subclasses.

Aplicável aos imóveis já classificados como ``contido_menor`` (imóvel do SICAR
contido numa parcela do INCRA bem maior). Refina esse grupo em:

  - ``contido_menor_grande``     : a fração do SICAR em relação ao INCRA-pai é
                                   alta (>= FRAC_GRANDE) — quase do tamanho da
                                   parcela de referência.
  - ``contido_menor_isolado``    : fração baixa e SEM sobreposição relevante a
                                   outros pequenos dentro da MESMA parcela-pai.
  - ``contido_menor_sobreposto`` : fração baixa e COM sobreposição a outros
                                   pequenos na mesma parcela-pai (indício de
                                   duplicidade/conflito cadastral).

Definições:
  - INCRA-pai : a parcela individual do INCRA com maior área de interseção
                com o imóvel do SICAR.
  - frac      : área(SICAR) / área(INCRA-pai), ambas geodésicas.
  - o teste de sobreposição entre pequenos usa um piso de PISO_SOBREP da área
    do menor, para ignorar encostas mínimas de borda.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections import defaultdict
from typing import Hashable

from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from .geometria import area_geodesica_m2, limpar_2d_valido


@dataclass(frozen=True)
class ParametrosSubdivisao:
    frac_grande: float = 0.50   # fração a partir da qual é "grande"
    piso_sobrep: float = 0.01   # piso de sobreposição entre pequenos (1%)


def _incra_pai(gx: BaseGeometry, ref_geoms, ref_areas, tree) -> tuple[int | None, float]:
    """Retorna (índice do INCRA-pai, área do pai) — parcela de maior interseção."""
    best_i, best_a = None, 0.0
    for pos in tree.query(gx):
        i = int(pos)
        gy = ref_geoms[i]
        if not gx.intersects(gy):
            continue
        inter = gx.intersection(gy)
        a = area_geodesica_m2(inter) if inter and not inter.is_empty else 0.0
        if a > best_a:
            best_a, best_i = a, i
    return best_i, (ref_areas[best_i] if best_i is not None else 0.0)


def subdividir_contido_menor(
    ids: list[Hashable],
    geoms_sicar: list[BaseGeometry],
    ref_geoms_incra: list[BaseGeometry],
    par: ParametrosSubdivisao = ParametrosSubdivisao(),
) -> dict[Hashable, str]:
    """Classifica cada imóvel ``contido_menor`` em uma das três subclasses.

    Parâmetros
    ----------
    ids : identificadores dos imóveis contido_menor.
    geoms_sicar : geometrias desses imóveis (mesma ordem de ``ids``).
    ref_geoms_incra : geometrias da referência INCRA da MESMA natureza
                      (pública ou privada) usada na classificação.

    Retorna ``{id: subclasse}``.
    """
    # Referência limpa + índice.
    ref_geoms, ref_areas = [], []
    for g in ref_geoms_incra:
        gg = limpar_2d_valido(g)
        if gg is None:
            continue
        ref_geoms.append(gg)
        ref_areas.append(area_geodesica_m2(gg))
    ref_tree = STRtree(ref_geoms) if ref_geoms else None

    # Fase 1: INCRA-pai + frac -> grupo A (grande) ou B (pequeno).
    geoms, areas = {}, {}
    frac, pai_idx = {}, {}
    grupoB_por_pai: dict[int, list[Hashable]] = defaultdict(list)
    subclasse: dict[Hashable, str] = {}

    for gid, g in zip(ids, geoms_sicar):
        gg = limpar_2d_valido(g)
        if gg is None or ref_tree is None:
            subclasse[gid] = "contido_menor_isolado"  # sem referência: trata como isolado
            continue
        a_s = area_geodesica_m2(gg)
        pi, a_pai = _incra_pai(gg, ref_geoms, ref_areas, ref_tree)
        fr = (a_s / a_pai) if a_pai > 0 else -1.0
        geoms[gid], areas[gid] = gg, a_s
        frac[gid], pai_idx[gid] = fr, pi
        if fr >= par.frac_grande:
            subclasse[gid] = "contido_menor_grande"
        else:
            if pi is not None:
                grupoB_por_pai[pi].append(gid)
            else:
                subclasse[gid] = "contido_menor_isolado"

    # Fase 2: entre os pequenos (grupo B) que dividem a mesma parcela-pai,
    # testa sobreposição mútua (piso relativo ao menor).
    for pi, membros in grupoB_por_pai.items():
        if len(membros) == 1:
            subclasse[membros[0]] = "contido_menor_isolado"
            continue
        gs = [geoms[m] for m in membros]
        tree = STRtree(gs)
        sobrepostos: set[Hashable] = set()
        for a_pos, mid in enumerate(membros):
            ga = geoms[mid]
            aa = areas[mid]
            for b_pos in tree.query(ga):
                b = int(b_pos)
                if b <= a_pos:
                    continue
                mid_b = membros[b]
                gb, ab = geoms[mid_b], areas[mid_b]
                if not ga.intersects(gb):
                    continue
                inter = ga.intersection(gb)
                ia = area_geodesica_m2(inter) if inter and not inter.is_empty else 0.0
                if ia > par.piso_sobrep * min(aa, ab):
                    sobrepostos.add(mid)
                    sobrepostos.add(mid_b)
        for m in membros:
            subclasse[m] = (
                "contido_menor_sobreposto" if m in sobrepostos
                else "contido_menor_isolado"
            )

    return subclasse
