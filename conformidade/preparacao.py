"""
preparacao.py — etapa 0: preparação a partir dos dados brutos do SICAR.

Ponto de partida do processo quando se usa o download oficial do SICAR
(https://consultapublica.car.gov.br/publico/estados/downloads), cujos planos de
informação vêm em pastas/shapefiles com nomes padronizados:

    APPS, AREA_CONSOLIDADA, AREA_IMOVEL, AREA_POUSIO, HIDROGRAFIA,
    RESERVA_LEGAL, SERVIDAO_ADMINISTRATIVA, USO_RESTRITO, VEGETACAO_NATIVA

Todos compartilham a chave ``cod_imovel``; ``AREA_IMOVEL`` traz a fase de
análise em ``des_condic``.

O que esta etapa faz (por estado):

  1. Lê ``AREA_IMOVEL`` e classifica cada imóvel em uma das quatro fases
     (ver :mod:`conformidade.fases`).
  2. DESCARTA os ``Cancelado``.
  3. Separa dois conjuntos de ``cod_imovel``:
       - ANALISADO      -> pacote para análises futuras;
       - EM/AGUARDANDO  -> pacote de trabalho desta análise.
  4. Grava dois GeoPackages:
       - ``<UF>_analisados.gpkg`` : AREA_IMOVEL (analisados) + TODOS os nove
         planos, filtrados pelos imóveis analisados. (Reservado para análises
         subsequentes — não é usado na conformidade.)
       - ``<UF>_trabalho.gpkg``   : AREA_IMOVEL (em análise + aguardando). As
         camadas temáticas NÃO entram aqui agora; só APPS/RESERVA_LEGAL/
         USO_RESTRITO dos imóveis "representantes" entram ao final da análise.

Os nomes de plano são configuráveis (:data:`PLANOS_PADRAO`) para acomodar
variações de organização dos arquivos.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import geopandas as gpd

from .io_dados import ler_camada, escrever_camada
from .fases import (
    classificar_fase, ANALISADO, CANCELADO, EM_ANALISE, AGUARDANDO,
)

# Nomes canônicos dos nove planos do SICAR.
PLANOS_PADRAO = (
    "APPS", "AREA_CONSOLIDADA", "AREA_IMOVEL", "AREA_POUSIO", "HIDROGRAFIA",
    "RESERVA_LEGAL", "SERVIDAO_ADMINISTRATIVA", "USO_RESTRITO",
    "VEGETACAO_NATIVA",
)

# Planos temáticos que serão anexados ao pacote de trabalho no FIM da análise,
# apenas para os imóveis "representantes".
PLANOS_TEMATICOS_FINAIS = ("APPS", "RESERVA_LEGAL", "USO_RESTRITO")


@dataclass
class ResultadoPreparacao:
    uf: str
    cods_analisado: set
    cods_em_analise: set
    cods_aguardando: set
    cods_cancelado: set
    gpkg_analisados: str
    gpkg_trabalho: str

    @property
    def cods_trabalho(self) -> set:
        return self.cods_em_analise | self.cods_aguardando

    def resumo(self) -> dict:
        return {
            "uf": self.uf,
            "analisado": len(self.cods_analisado),
            "em_analise": len(self.cods_em_analise),
            "aguardando": len(self.cods_aguardando),
            "cancelado_descartado": len(self.cods_cancelado),
            "gpkg_analisados": self.gpkg_analisados,
            "gpkg_trabalho": self.gpkg_trabalho,
        }


def preparar_estado(
    planos: dict[str, str],
    uf: str,
    saida_dir: str,
    col_cod: str = "cod_imovel",
    col_fase: str = "des_condic",
) -> ResultadoPreparacao:
    """Executa a etapa 0 para um estado.

    Parâmetros
    ----------
    planos : mapa ``{NOME_DO_PLANO: caminho_do_arquivo}``. Deve conter ao menos
             ``AREA_IMOVEL``. Os demais planos entram no pacote de analisados;
             a ausência de algum é tolerada (apenas avisada).
    uf : sigla do estado (usada nos nomes dos arquivos e camadas).
    saida_dir : diretório onde gravar os dois GeoPackages.
    col_cod, col_fase : nomes das colunas de código e de fase.

    Retorna :class:`ResultadoPreparacao`.
    """
    os.makedirs(saida_dir, exist_ok=True)
    if "AREA_IMOVEL" not in planos:
        raise KeyError("O plano 'AREA_IMOVEL' é obrigatório na preparação.")

    # 1) Ler imóveis e classificar por fase.
    imoveis = ler_camada(planos["AREA_IMOVEL"])
    if col_fase not in imoveis.columns:
        raise KeyError(
            f"Coluna de fase '{col_fase}' ausente em AREA_IMOVEL. "
            f"Colunas: {list(imoveis.columns)}"
        )
    fases = imoveis[col_fase].map(classificar_fase)

    # IMPORTANTE: filtramos pela FASE DE CADA LINHA, não pelo conjunto de
    # códigos. O SICAR pode ter o mesmo cod_imovel em linhas de fases
    # diferentes (ex.: "Cancelado por duplicidade" — que É, por definição, um
    # cadastro duplicado). Filtrar por código traria a linha cancelada junto
    # com a válida. Filtrar por fase da linha descarta cada linha cancelada.
    def cods_da_fase(rotulo):
        return set(imoveis.loc[fases == rotulo, col_cod])

    cods_analisado = cods_da_fase(ANALISADO)
    cods_em = cods_da_fase(EM_ANALISE)
    cods_agu = cods_da_fase(AGUARDANDO)
    cods_cancel = cods_da_fase(CANCELADO)

    # Máscaras por fase da LINHA (não por código).
    mask_analisado = fases == ANALISADO
    mask_trabalho = fases.isin([EM_ANALISE, AGUARDANDO])

    # 2) Pacote ANALISADOS: AREA_IMOVEL(linhas analisadas) + planos filtrados
    #    pelos códigos analisados.
    gpkg_ana = os.path.join(saida_dir, f"{uf}_analisados.gpkg")
    _gravar_pacote(planos, cods_analisado, gpkg_ana, col_cod,
                   imoveis_ja_lidos=imoveis[mask_analisado])

    # 3) Pacote TRABALHO: apenas as LINHAS em análise + aguardando.
    gpkg_tra = os.path.join(saida_dir, f"{uf}_trabalho.gpkg")
    trabalho = imoveis[mask_trabalho].copy()
    # marca a fase canônica para uso posterior
    trabalho["fase"] = trabalho[col_fase].map(classificar_fase)
    escrever_camada(trabalho, gpkg_tra, "AREA_IMOVEL")

    return ResultadoPreparacao(
        uf, cods_analisado, cods_em, cods_agu, cods_cancel, gpkg_ana, gpkg_tra,
    )


def _gravar_pacote(planos, cods, caminho_gpkg, col_cod, imoveis_ja_lidos=None):
    """Grava um GeoPackage com todos os planos filtrados por ``cods``."""
    import warnings
    for nome, caminho in planos.items():
        if nome == "AREA_IMOVEL" and imoveis_ja_lidos is not None:
            sub = imoveis_ja_lidos
        else:
            try:
                gdf = ler_camada(caminho)
            except Exception as e:
                warnings.warn(f"Plano '{nome}' não pôde ser lido ({e}); ignorado.")
                continue
            if col_cod not in gdf.columns:
                warnings.warn(f"Plano '{nome}' sem coluna '{col_cod}'; ignorado.")
                continue
            sub = gdf[gdf[col_cod].isin(cods)]
        if len(sub) > 0:
            escrever_camada(sub, caminho_gpkg, nome)
