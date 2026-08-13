"""
fases.py — identificação da fase de análise do imóvel do SICAR (``des_condic``).

O campo ``des_condic`` do SICAR (ver dicionário de dados) traz a condição da
análise em texto livre, com variações ("derivações"). Na prática existem quatro
fases, todas identificáveis por uma palavra-chave presente no texto:

  - ANALISADO   : imóvel já analisado pelo órgão (qualquer derivação).
  - CANCELADO   : cadastro cancelado (qualquer derivação) — DESCARTADO.
  - EM_ANALISE  : "Em análise".
  - AGUARDANDO  : "Aguardando análise".

A identificação é por PALAVRA-CHAVE (``contém``), tolerante a acentuação e
caixa, cobrindo tanto o prefixo quanto as derivações.
"""

from __future__ import annotations

import unicodedata

# Rótulos canônicos das fases.
ANALISADO = "Analisado"
CANCELADO = "Cancelado"
EM_ANALISE = "Em Análise"
AGUARDANDO = "Aguardando Análise"

# Fases que ENTRAM na análise de conformidade (fases de trabalho).
FASES_TRABALHO = (EM_ANALISE, AGUARDANDO)


def _normalizar(texto: str) -> str:
    """Minúsculas sem acento, para casar palavras-chave de forma robusta."""
    if texto is None:
        return ""
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return t.strip().lower()


def classificar_fase(des_condic: str) -> str | None:
    """Mapeia um valor de ``des_condic`` para uma das quatro fases canônicas.

    Retorna o rótulo canônico (:data:`ANALISADO`, :data:`CANCELADO`,
    :data:`EM_ANALISE`, :data:`AGUARDANDO`) ou ``None`` se não reconhecer.

    A ordem de teste importa: "cancelado" e "analisado" são checados primeiro
    porque são palavras-raiz inequívocas; depois distinguem-se as duas fases
    pendentes por "aguardando" vs "analise".
    """
    t = _normalizar(des_condic)
    if not t:
        return None
    if "cancelad" in t:            # cancelado, cancelada, canceladas...
        return CANCELADO
    if "analisad" in t:            # analisado, analisada, analisados...
        return ANALISADO
    if "aguardando" in t:          # aguardando análise (e derivações)
        return AGUARDANDO
    if "em analise" in t or "em análise" in _normalizar(des_condic):
        return EM_ANALISE
    # fallback: "analise" sem "aguardando" e sem "analisad" => Em Análise
    if "analise" in t:
        return EM_ANALISE
    return None


def eh_fase_trabalho(des_condic: str) -> bool:
    """True se o imóvel está em fase de trabalho (Em Análise ou Aguardando)."""
    return classificar_fase(des_condic) in FASES_TRABALHO


def eh_analisado(des_condic: str) -> bool:
    """True se o imóvel está na fase Analisado (qualquer derivação)."""
    return classificar_fase(des_condic) == ANALISADO
