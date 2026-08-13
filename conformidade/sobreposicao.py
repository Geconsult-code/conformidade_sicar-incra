"""
sobreposicao.py — filtro de sobreposição espacial entre imóveis (SICAR × SICAR).

Eixo ORTOGONAL à classificação de coerência (``motivo``). Serve para eliminar a
dupla contagem de área numa análise posterior (ex.: somar APP/RL/AUR): dois
imóveis coerentes podem ocupar a mesma porção do território, e nesse caso só um
deve ser mantido.

Métrica (definida e validada com o usuário):

  Para o imóvel MENOR ``X``, mede-se, contra cada imóvel MAIOR ``Y``:

        frac(X, Y) = área(X ∩ Y) / área(X)

  ``frac_max(X)`` é a maior cobertura de ``X`` por um único imóvel maior.
  O "pai" é sempre o imóvel de MAIOR tamanho (nunca é marcado como redundante),
  presumivelmente o mais fiel à referência do INCRA.

Classe resultante (campo ``classe_espacial``):

  - ``redundante_sobreposto`` : frac_max >= limiar
  - ``representante``         : caso contrário

O campo numérico ``frac_max`` é gravado junto: permite RECALIBRAR o limiar
depois, apenas filtrando, sem reprocessar a geometria. ``pai_cod`` guarda o
código do imóvel maior que mais cobre ``X``.

Conservação: todo imóvel recebe uma classe; a soma
(representantes + redundantes) é igual ao total de entrada.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Hashable

from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from .geometria import area_geodesica_m2, limpar_2d_valido


@dataclass
class ResultadoSobreposicao:
    """Saída por imóvel: fração máxima, código do pai e classe espacial."""
    frac_max: float
    pai_cod: Hashable | None
    classe_espacial: str


def calcular_sobreposicao(
    ids: list[Hashable],
    geometrias: list[BaseGeometry],
    limiar: float = 0.70,
) -> dict[Hashable, ResultadoSobreposicao]:
    """Calcula ``frac_max``, ``pai_cod`` e ``classe_espacial`` para cada imóvel.

    Parâmetros
    ----------
    ids : lista de identificadores (ex.: ``cod_imovel``), únicos.
    geometrias : lista de geometrias na mesma ordem de ``ids`` (EPSG:4674).
    limiar : fração a partir da qual o imóvel menor é ``redundante_sobreposto``.

    Regra do "pai" (imóvel maior):
      - só compara ``X`` contra ``Y`` se área(Y) > área(X);
      - em empate exato de área, mantém-se um determinístico (o de ``id`` maior),
        para nunca marcar ambos.

    O ``frac_max`` gravado independe do ``limiar`` — permite recalibração
    posterior com :func:`reclassificar`.
    """
    # Prepara geometrias limpas e áreas.
    geoms: list[BaseGeometry | None] = []
    areas: list[float] = []
    for g in geometrias:
        gg = limpar_2d_valido(g)
        geoms.append(gg)
        areas.append(area_geodesica_m2(gg) if gg is not None else 0.0)

    # Índice espacial só com as geometrias válidas.
    validos = [i for i, g in enumerate(geoms) if g is not None]
    tree = STRtree([geoms[i] for i in validos]) if validos else None
    # Mapa posição-no-índice -> posição-original.
    pos_para_orig = {pos: i for pos, i in enumerate(validos)}

    resultado: dict[Hashable, ResultadoSobreposicao] = {}

    for i, gid in enumerate(ids):
        gx = geoms[i]
        ax = areas[i]
        if gx is None or ax <= 0 or tree is None:
            resultado[gid] = ResultadoSobreposicao(0.0, None, "representante")
            continue

        best_frac = 0.0
        best_pai: Hashable | None = None
        for pos in tree.query(gx):
            j = pos_para_orig[int(pos)]
            if j == i:
                continue
            ay = areas[j]
            # "pai" é sempre o maior; empate resolvido por id determinístico.
            if ay < ax:
                continue
            if ay == ax and _menor_ou_igual(ids[j], gid):
                continue
            gy = geoms[j]
            if gy is None or not gx.intersects(gy):
                continue
            inter = gx.intersection(gy)
            ia = area_geodesica_m2(inter) if inter and not inter.is_empty else 0.0
            frac = ia / ax
            if frac > best_frac:
                best_frac = frac
                best_pai = ids[j]

        classe = "redundante_sobreposto" if best_frac >= limiar else "representante"
        resultado[gid] = ResultadoSobreposicao(round(best_frac, 4), best_pai, classe)

    return resultado


def reclassificar(
    frac_max_por_id: dict[Hashable, float],
    limiar: float,
) -> dict[Hashable, str]:
    """Recalcula apenas ``classe_espacial`` a partir de ``frac_max`` já gravado.

    Não toca em geometria — é a operação barata de recalibração de limiar.
    """
    return {
        gid: ("redundante_sobreposto" if fr >= limiar else "representante")
        for gid, fr in frac_max_por_id.items()
    }


def sobreposicao_contra_externo(
    ids: list[Hashable],
    geometrias: list[BaseGeometry],
    geometrias_externas: list[BaseGeometry],
    limiar: float = 0.10,
) -> dict[Hashable, ResultadoSobreposicao]:
    """Marca imóveis que se sobrepõem a um conjunto EXTERNO com prioridade.

    Usado no filtro final: os imóveis de trabalho (Em Análise + Aguardando) são
    testados contra os imóveis já ``Analisado``. O conjunto externo tem
    PRIORIDADE — nunca é removido; apenas os imóveis de ``ids`` podem ser
    marcados como ``redundante_sobreposto``.

    Para cada imóvel ``X`` de ``ids``:
        frac(X) = área(X ∩ Y) / área(X), tomada sobre o Y externo de maior
        interseção. Se ``frac >= limiar`` -> ``redundante_sobreposto``
        (pai_cod = None, pois o pai é externo).

    Diferente de :func:`calcular_sobreposicao`, aqui NÃO se exige que o externo
    seja maior: um imóvel já analisado prevalece independentemente do tamanho,
    porque representa uma decisão do órgão competente.
    """
    ext = [limpar_2d_valido(g) for g in geometrias_externas]
    ext = [g for g in ext if g is not None]
    tree = STRtree(ext) if ext else None

    resultado: dict[Hashable, ResultadoSobreposicao] = {}
    for gid, g in zip(ids, geometrias):
        gx = limpar_2d_valido(g)
        if gx is None or tree is None:
            resultado[gid] = ResultadoSobreposicao(0.0, None, "representante")
            continue
        ax = area_geodesica_m2(gx)
        if ax <= 0:
            resultado[gid] = ResultadoSobreposicao(0.0, None, "representante")
            continue
        best = 0.0
        for pos in tree.query(gx):
            gy = ext[int(pos)]
            if not gx.intersects(gy):
                continue
            inter = gx.intersection(gy)
            ia = area_geodesica_m2(inter) if inter and not inter.is_empty else 0.0
            frac = ia / ax
            if frac > best:
                best = frac
        classe = "redundante_sobreposto" if best >= limiar else "representante"
        resultado[gid] = ResultadoSobreposicao(round(best, 4), None, classe)
    return resultado


def _menor_ou_igual(a: Hashable, b: Hashable) -> bool:
    """Comparação determinística para desempate de áreas iguais.

    Retorna True quando ``a`` deve ser considerado "não maior" que ``b``
    (isto é, ``a`` NÃO serve de pai para ``b`` no empate). Usa a ordem natural
    quando possível; senão, compara as representações em texto.
    """
    try:
        return a <= b  # type: ignore[operator]
    except TypeError:
        return str(a) <= str(b)
