"""
recorte.py — seleção das feições temáticas (APP, RL, AUR) dos imóveis coerentes.

As camadas de APP (Área de Preservação Permanente), RL (Reserva Legal) e AUR
(Área de Uso Restrito) do CAR trazem o mesmo identificador de imóvel
(``cod_imovel``) das bases do SICAR. Este módulo FILTRA essas feições, mantendo
apenas as pertencentes a um conjunto de imóveis (tipicamente os "coerentes"), e,
opcionalmente, agrega os atributos de classificação (``motivo``,
``classe_espacial``, ``frac_max``, ``pai_cod``) por junção em ``cod_imovel``.

É um recorte por ATRIBUTO (junção pela chave), não por geometria — rápido e
exato. A geometria das feições temáticas é preservada integralmente.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Any

import geopandas as gpd

from .io_dados import concatenar


def filtrar_tematicas(
    camadas: Iterable[gpd.GeoDataFrame],
    cods_coerentes: set,
    col_cod: str = "cod_imovel",
    rotulos: Iterable[str] | None = None,
    atributos_por_cod: Mapping[Any, Mapping[str, Any]] | None = None,
) -> gpd.GeoDataFrame:
    """Filtra e consolida feições temáticas dos imóveis em ``cods_coerentes``.

    Parâmetros
    ----------
    camadas : GeoDataFrames de APP/RL/AUR (uma ou várias; podem vir por
              subtipo e por fase — todas são concatenadas).
    cods_coerentes : conjunto de ``cod_imovel`` a manter.
    col_cod : nome da coluna com o identificador do imóvel.
    rotulos : rótulo de proveniência por camada (mesma ordem de ``camadas``),
              gravado na coluna ``origem_camada`` (opcional).
    atributos_por_cod : mapa ``{cod_imovel: {coluna: valor}}`` para anexar os
              campos de classificação (``motivo``, ``classe_espacial`` etc.).

    Retorna um único GeoDataFrame com todas as feições selecionadas.
    """
    camadas = list(camadas)
    rotulos = list(rotulos) if rotulos is not None else [None] * len(camadas)

    selecionadas = []
    for gdf, rotulo in zip(camadas, rotulos):
        if col_cod not in gdf.columns:
            raise KeyError(
                f"Camada temática sem a coluna '{col_cod}'. "
                f"Colunas disponíveis: {list(gdf.columns)}"
            )
        sub = gdf[gdf[col_cod].isin(cods_coerentes)].copy()
        if rotulo is not None:
            sub["origem_camada"] = rotulo
        selecionadas.append(sub)

    out = concatenar(selecionadas)
    if len(out) == 0:
        return out

    # Anexa atributos de classificação por junção na chave.
    if atributos_por_cod:
        colunas: set[str] = set()
        for v in atributos_por_cod.values():
            colunas.update(v.keys())
        for col in colunas:
            out[col] = out[col_cod].map(
                lambda c: atributos_por_cod.get(c, {}).get(col)
            )

    return out
