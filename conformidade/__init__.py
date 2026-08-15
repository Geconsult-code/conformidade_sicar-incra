"""
conformidade — análise de conformidade (coerência) entre imóveis do SICAR e a
delimitação fundiária do INCRA (SIGEF + SNCI), com filtro de sobreposição
espacial e recorte temático (APP/RL/AUR).

Biblioteca reutilizável. Para uso por linha de comando, veja ``conformidade.cli``
ou o executável ``conformidade``.

Exemplo mínimo (biblioteca)::

    from conformidade.io_dados import ler_camada
    from conformidade.pipeline import (
        ConfigPipeline, montar_referencia, classificar_camada_sicar,
        aplicar_sobreposicao,
    )

    sicar = ler_camada("SICAR_Aguardando.shp")
    sigef = ler_camada("SIGEF_Privado.shp")
    snci  = ler_camada("SNCI_Privado.shp")

    ref = montar_referencia([sigef, snci])
    cfg = ConfigPipeline(limiar_sobreposicao=0.70)

    res = classificar_camada_sicar(sicar, ref, cfg, natureza="Privado")
    coer = aplicar_sobreposicao(res.coerentes, cfg)
"""

from .geometria import area_geodesica_m2, limpar_2d_valido, CRS_TRABALHO
from .classificacao import (
    ReferenciaINCRA, Limiares, classificar_imovel, CAMPOS_RESULTADO,
)
from .sobreposicao import (
    calcular_sobreposicao, reclassificar, ResultadoSobreposicao,
    sobreposicao_contra_externo,
)
from .subdivisao import subdividir_contido_menor, ParametrosSubdivisao
from .recorte import filtrar_tematicas
from .fases import (
    classificar_fase, eh_fase_trabalho, eh_analisado,
    ANALISADO, CANCELADO, EM_ANALISE, AGUARDANDO, FASES_TRABALHO,
)
from .preparacao import (
    preparar_estado, ResultadoPreparacao,
    PLANOS_PADRAO, PLANOS_TEMATICOS_FINAIS,
)
from .pipeline import (
    ConfigPipeline, ResultadoNatureza, montar_referencia,
    classificar_camada_sicar, aplicar_sobreposicao, aplicar_filtro_analisados,
)

__version__ = "0.3.0"

__all__ = [
    "area_geodesica_m2", "limpar_2d_valido", "CRS_TRABALHO",
    "ReferenciaINCRA", "Limiares", "classificar_imovel", "CAMPOS_RESULTADO",
    "calcular_sobreposicao", "reclassificar", "ResultadoSobreposicao",
    "sobreposicao_contra_externo",
    "subdividir_contido_menor", "ParametrosSubdivisao",
    "filtrar_tematicas",
    "classificar_fase", "eh_fase_trabalho", "eh_analisado",
    "ANALISADO", "CANCELADO", "EM_ANALISE", "AGUARDANDO", "FASES_TRABALHO",
    "preparar_estado", "ResultadoPreparacao",
    "PLANOS_PADRAO", "PLANOS_TEMATICOS_FINAIS",
    "ConfigPipeline", "ResultadoNatureza", "montar_referencia",
    "classificar_camada_sicar", "aplicar_sobreposicao", "aplicar_filtro_analisados",
    "__version__",
]
