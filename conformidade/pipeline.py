"""
pipeline.py — orquestração modular da análise de conformidade SICAR × INCRA.

Etapas (cada uma pode ser ligada/desligada):

  1. coerencia   : classifica cada imóvel do SICAR contra a referência INCRA,
                   separadamente para as naturezas PÚBLICA e PRIVADA.
  2. subdivisao  : (opcional) subdivide o ``contido_menor`` dos COERENTES em
                   grande / isolado / sobreposto.
  3. sobreposicao: (opcional) marca redundância espacial SICAR×SICAR nos
                   coerentes (campos frac_max, pai_cod, classe_espacial).
  4. recorte     : (opcional) filtra APP/RL/AUR dos imóveis coerentes.

A separação por natureza (pública/privada) reproduz a decisão metodológica
validada: misturar as duas força comparação de forma e gera contido_menor em
massa. Rode a natureza que interessa (por padrão, PRIVADA) ou ambas.

Este módulo é a "biblioteca": funções puras que recebem GeoDataFrames e
devolvem GeoDataFrames/dicionários. A CLI (cli.py) apenas lê arquivos, chama
estas funções e grava as saídas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import geopandas as gpd

from .classificacao import ReferenciaINCRA, Limiares, classificar_imovel, CAMPOS_RESULTADO
from .sobreposicao import calcular_sobreposicao
from .subdivisao import subdividir_contido_menor, ParametrosSubdivisao
from .io_dados import concatenar, verificar_conservacao


@dataclass
class ConfigPipeline:
    """Configuração de uma execução da pipeline."""
    col_cod: str = "cod_imovel"
    limiares: Limiares = field(default_factory=Limiares)
    subdividir: bool = True
    par_subdivisao: ParametrosSubdivisao = field(default_factory=ParametrosSubdivisao)
    calcular_sobreposicao: bool = True
    limiar_sobreposicao: float = 0.70
    # Limiar do filtro FINAL contra os imóveis já "Analisado" (etapa final).
    # 0,30 = calibrado no Pará: elimina imóveis que sobrepõem 1/3 ou mais de um
    # imóvel analisado (duplicatas reais), preservando os que só encostam.
    limiar_vs_analisado: float = 0.30


@dataclass
class ResultadoNatureza:
    """Resultado da classificação de uma natureza (pública ou privada)."""
    natureza: str
    coerentes: gpd.GeoDataFrame
    incoerentes: gpd.GeoDataFrame
    total_entrada: int

    def conservacao_ok(self) -> bool:
        ok, _ = verificar_conservacao(
            self.total_entrada, len(self.coerentes), len(self.incoerentes)
        )
        return ok


def classificar_camada_sicar(
    sicar: gpd.GeoDataFrame,
    referencia: ReferenciaINCRA,
    cfg: ConfigPipeline,
    natureza: str,
) -> ResultadoNatureza:
    """Etapa 1 (+2): classifica um GeoDataFrame do SICAR contra uma referência.

    Adiciona as colunas de ``CAMPOS_RESULTADO`` + ``tipo_incra``. Se
    ``cfg.subdividir``, refina o ``contido_menor`` dos coerentes.
    """
    registros: list[dict[str, Any]] = []
    for geom in sicar.geometry:
        registros.append(classificar_imovel(geom, referencia, cfg.limiares))

    out = sicar.copy().reset_index(drop=True)
    for campo in CAMPOS_RESULTADO:
        out[campo] = [r[campo] for r in registros]
    out["tipo_incra"] = natureza

    # Etapa 2: subdivisão do contido_menor (apenas nos coerentes).
    if cfg.subdividir:
        mask_cm = (out["classe"] == "Coerente") & (out["motivo"] == "contido_menor")
        if mask_cm.any():
            sub_ids = list(out.loc[mask_cm, cfg.col_cod])
            sub_geoms = list(out.loc[mask_cm, "geometry"])
            mapa = subdividir_contido_menor(
                sub_ids, sub_geoms, referencia.geoms, cfg.par_subdivisao
            )
            out.loc[mask_cm, "motivo"] = out.loc[mask_cm, cfg.col_cod].map(
                lambda c: mapa.get(c, "contido_menor")
            )

    coer = out[out["classe"] == "Coerente"].copy()
    inco = out[out["classe"] == "Incoerente"].copy()
    return ResultadoNatureza(natureza, coer, inco, len(sicar))


def aplicar_sobreposicao(
    coerentes: gpd.GeoDataFrame,
    cfg: ConfigPipeline,
) -> gpd.GeoDataFrame:
    """Etapa 3: marca redundância espacial nos imóveis coerentes.

    Adiciona as colunas ``frac_max``, ``pai_cod`` e ``classe_espacial``.
    Opera sobre o conjunto TODO de coerentes (todas as classes de motivo),
    pois a sobreposição é ortogonal ao motivo.
    """
    ids = list(coerentes[cfg.col_cod])
    geoms = list(coerentes.geometry)
    res = calcular_sobreposicao(ids, geoms, cfg.limiar_sobreposicao)

    out = coerentes.copy()
    out["frac_max"] = out[cfg.col_cod].map(lambda c: res[c].frac_max)
    out["pai_cod"] = out[cfg.col_cod].map(lambda c: res[c].pai_cod)
    out["classe_espacial"] = out[cfg.col_cod].map(lambda c: res[c].classe_espacial)
    return out


def aplicar_filtro_analisados(
    coerentes: gpd.GeoDataFrame,
    analisados: gpd.GeoDataFrame,
    cfg: ConfigPipeline,
) -> gpd.GeoDataFrame:
    """Etapa final: remove os representantes que se sobrepõem a imóveis
    já ``Analisado`` (que têm prioridade e nunca são removidos).

    Espera que ``coerentes`` já tenha passado por :func:`aplicar_sobreposicao`
    (coluna ``classe_espacial``). Acrescenta:
      - ``vs_analisado``   : 'sobrepoe_analisado' ou 'livre';
      - ``frac_analisado`` : cobertura máxima por um imóvel analisado;
      - ``selecao_final``  : 'Representante (manter)' apenas se for
        ``representante`` na sobreposição interna E ``livre`` frente aos
        analisados; caso contrário registra o motivo da exclusão
        ('redundante_interno' ou 'sobrepoe_analisado').

    Conservação: toda linha recebe ``selecao_final``.
    """
    from .sobreposicao import sobreposicao_contra_externo

    out = coerentes.copy()
    if analisados is None or len(analisados) == 0:
        out["vs_analisado"] = "livre"
        out["frac_analisado"] = 0.0
    else:
        ids = list(out[cfg.col_cod])
        geoms = list(out.geometry)
        res = sobreposicao_contra_externo(
            ids, geoms, list(analisados.geometry), cfg.limiar_vs_analisado,
        )
        out["frac_analisado"] = out[cfg.col_cod].map(lambda c: res[c].frac_max)
        out["vs_analisado"] = out[cfg.col_cod].map(
            lambda c: "sobrepoe_analisado"
            if res[c].classe_espacial == "redundante_sobreposto" else "livre"
        )

    def _selecao(row):
        if row.get("classe_espacial", "representante") != "representante":
            return "redundante_interno"
        if row["vs_analisado"] == "sobrepoe_analisado":
            return "sobrepoe_analisado"
        return "Representante (manter)"

    out["selecao_final"] = out.apply(_selecao, axis=1)
    return out


def montar_referencia(
    incra_gdfs: list[gpd.GeoDataFrame],
) -> ReferenciaINCRA:
    """Constrói a :class:`ReferenciaINCRA` a partir de camadas do INCRA."""
    geoms = []
    for gdf in incra_gdfs:
        geoms.extend(list(gdf.geometry))
    return ReferenciaINCRA(geoms)
