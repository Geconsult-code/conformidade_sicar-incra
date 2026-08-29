r"""
conformidade_notificacao.py — roda a conformidade SICAR × INCRA sobre os
imóveis na fase "Analisado, aguardando atendimento a notificação" (a categoria
de "analisado com pendências"), estado por estado.

Diferença para o fluxo principal: aqui o universo a classificar é essa subfase
específica dos ANALISADOS (não os Em Análise/Aguardando). O filtro de
sobreposição usa os DEMAIS imóveis analisados como referência de prioridade
(eles vencem e nunca são removidos) — mesma mecânica do filtro vs Analisados do
pipeline original. A saída traz SÓ as camadas de imóveis (Coerentes/Incoerentes
com selecao_final); sem recorte de APP/RL/USO_RESTRITO.

Para cada estado (pasta _saida_<UF> em PASTA_BASE):
  1. lê <UF>_analisados.gpkg (camada AREA_IMOVEL);
  2. separa: universo = "aguardando atendimento a notificação";
             prioridade = os demais analisados;
  3. classifica o universo contra o INCRA privado (SIGEF+SNCI);
  4. aplica sobreposição interna + filtro contra os demais analisados;
  5. grava <UF>_notificacao_Privado.gpkg dentro de _saida_<UF>, com as camadas
     <UF>_Notificacao_Coerentes e <UF>_Notificacao_Incoerentes.

COMO USAR
---------
1. Confira os caminhos na seção CONFIG.
2. Com o ambiente 'geo' ativo (o mesmo do repositório de conformidade):
       python conformidade_notificacao.py
   Para validar, deixe SOMENTE_ESTES = ["AC"]; depois esvazie para todos.
"""

from __future__ import annotations

import os
import glob
import unicodedata
from datetime import datetime

import geopandas as gpd

from conformidade.io_dados import ler_camada, escrever_camada
from conformidade.pipeline import (
    ConfigPipeline, montar_referencia, classificar_camada_sicar,
    aplicar_sobreposicao, aplicar_filtro_analisados,
)

# =============================== CONFIG ===============================
PASTA_BASE = r"C:\Users\User\Dropbox\#CONSULTANCY\PLANAVEG\GEODATABASE\INCRA-CAR"
PASTA_INCRA = r"C:\Users\User\Dropbox\Geoinformation\GEOINFO BRASIL\INCRA"

# Deixe vazio para TODOS os estados; ou liste siglas (ex.: ["AC"]) para validar.
SOMENTE_ESTES: list[str] = ["AC"]

# Texto que identifica a fase-alvo (casado de forma tolerante a acento/caixa).
# "Analisado, aguardando atendimento a notificacao".
CHAVES_ALVO = ["analisado", "aguardando atendimento a notificacao"]

NATUREZA = "Privado"
COL_FASE = "des_condic"
CAM_IMOVEIS = "AREA_IMOVEL"
# =====================================================================


def _norm(txt) -> str:
    if txt is None:
        return ""
    t = unicodedata.normalize("NFKD", str(txt))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return t.strip().lower()


def eh_alvo(des_condic) -> bool:
    """True se o des_condic é a fase-alvo (contém todas as chaves)."""
    t = _norm(des_condic)
    return all(k in t for k in CHAVES_ALVO)


def achar_incra(uf: str) -> list[gpd.GeoDataFrame]:
    """Lê SIGEF_Privado_<UF>.shp e SNCI_Privado_<UF>.shp (os que existirem)."""
    camadas = []
    for prefixo in ("SIGEF_Privado", "SNCI_Privado"):
        caminho = os.path.join(PASTA_INCRA, f"{prefixo}_{uf}.shp")
        if os.path.exists(caminho):
            camadas.append(ler_camada(caminho))
    return camadas


def processar_uf(uf: str) -> dict:
    """Roda a conformidade da fase-alvo para um estado. Lança exceção em erro."""
    gpkg_ana = os.path.join(PASTA_BASE, f"_saida_{uf}", f"{uf}_analisados.gpkg")
    if not os.path.exists(gpkg_ana):
        raise FileNotFoundError(f"{uf}_analisados.gpkg não encontrado "
                                f"(estado sem fase Analisado?)")

    analisados = ler_camada(gpkg_ana, CAM_IMOVEIS)
    if COL_FASE not in analisados.columns:
        raise KeyError(f"coluna '{COL_FASE}' ausente em {uf}_analisados.gpkg")

    mask_alvo = analisados[COL_FASE].map(eh_alvo)
    universo = analisados[mask_alvo].copy()      # a classificar
    prioridade = analisados[~mask_alvo].copy()   # demais analisados (filtro)

    if len(universo) == 0:
        return {"uf": uf, "alvo": 0, "coerentes": 0, "incoerentes": 0,
                "manter": 0, "aviso": "nenhum imóvel na fase-alvo"}

    # referência INCRA privado
    incra_gdfs = achar_incra(uf)
    if not incra_gdfs:
        raise FileNotFoundError(f"INCRA privado de {uf} não encontrado")
    referencia = montar_referencia(incra_gdfs)

    cfg = ConfigPipeline()  # limiares padrão (limiar_vs_analisado=0.30, etc.)

    # 1) coerência (+ subdivisão)
    res = classificar_camada_sicar(universo, referencia, cfg, natureza=NATUREZA)
    # 2) sobreposição interna (entre os próprios imóveis da fase-alvo)
    coer = aplicar_sobreposicao(res.coerentes, cfg)
    # 3) filtro contra os DEMAIS analisados (prioridade)
    coer = aplicar_filtro_analisados(coer, prioridade, cfg)

    # grava só as camadas de imóveis
    saida = os.path.join(PASTA_BASE, f"_saida_{uf}",
                         f"{uf}_notificacao_{NATUREZA}.gpkg")
    if os.path.exists(saida):
        os.remove(saida)
    escrever_camada(coer, saida, f"{uf}_Notificacao_Coerentes")
    escrever_camada(res.incoerentes, saida, f"{uf}_Notificacao_Incoerentes")

    manter = int((coer["selecao_final"] == "Representante (manter)").sum())
    return {"uf": uf, "alvo": len(universo),
            "coerentes": len(res.coerentes), "incoerentes": len(res.incoerentes),
            "manter": manter, "saida": saida}


def main() -> int:
    saidas = sorted(glob.glob(os.path.join(PASTA_BASE, "_saida_*")))
    alvos = []
    for d in saidas:
        uf = os.path.basename(d).replace("_saida_", "").upper()
        if SOMENTE_ESTES and uf not in SOMENTE_ESTES:
            continue
        alvos.append(uf)

    print(f"Estados a processar ({len(alvos)}): {', '.join(alvos)}")
    print(f"Início: {datetime.now():%H:%M:%S}\n")

    sucesso, falhas = [], []
    for uf in alvos:
        print(f"  [{uf}] processando fase-alvo...", flush=True)
        try:
            r = processar_uf(uf)
            if r.get("aviso"):
                print(f"       (aviso: {r['aviso']})", flush=True)
            else:
                print(f"       alvo={r['alvo']} | coerentes={r['coerentes']} "
                      f"| incoerentes={r['incoerentes']} | manter={r['manter']}",
                      flush=True)
            sucesso.append(uf)
        except Exception as e:
            print(f"       !! ERRO: {e}", flush=True)
            falhas.append((uf, str(e)))

    print(f"\n{'#'*60}\n  RELATÓRIO ({datetime.now():%H:%M:%S})\n{'#'*60}")
    print(f"Sucesso ({len(sucesso)}): {', '.join(sucesso) or '—'}")
    if falhas:
        print(f"Falhas ({len(falhas)}):")
        for uf, msg in falhas:
            print(f"  {uf}: {msg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
