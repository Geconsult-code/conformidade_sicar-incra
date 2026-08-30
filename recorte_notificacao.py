r"""
recorte_notificacao.py — recorta as camadas temáticas APP / RESERVA_LEGAL /
USO_RESTRITO para os imóveis "Representante (manter)" da análise de conformidade
dos "Analisado, aguardando atendimento a notificação" (conformidade_notificacao.py).

Como o <UF>_analisados.gpkg guarda apenas o AREA_IMOVEL (sem os planos
temáticos), as APP/RL/AUR são lidas da FONTE BRUTA do SICAR
(BASE_CAR_ESTADOS_05_2026\<ESTADO>\), descompactando os .zip e juntando os
pedaços fatiados — a mesma lógica do processar_lote.py do fluxo principal.

Para cada estado:
  1. lê <UF>_notificacao_Privado.gpkg (camada <UF>_Notificacao_Coerentes) e
     seleciona os cod_imovel com selecao_final == "Representante (manter)";
  2. descompacta APPS / RESERVA_LEGAL / USO_RESTRITO do bruto e concatena;
  3. filtra as feições temáticas por esses cod_imovel (descartando canceladas,
     por segurança);
  4. grava as camadas APPS / RESERVA_LEGAL / USO_RESTRITO no MESMO
     <UF>_notificacao_Privado.gpkg.

COMO USAR
---------
1. Confira os caminhos na seção CONFIG.
2. Ambiente 'geo' ativo:
       python recorte_notificacao.py
   Valide com SOMENTE_ESTES = ["AC"]; depois esvazie para todos.
"""

from __future__ import annotations

import os
import glob
import zipfile
import unicodedata
from datetime import datetime

import geopandas as gpd
import pandas as pd

from conformidade.io_dados import ler_camada, escrever_camada
from conformidade.fases import classificar_fase, CANCELADO

# =============================== CONFIG ===============================
PASTA_BASE = r"C:\Users\User\Dropbox\#CONSULTANCY\PLANAVEG\GEODATABASE\INCRA-CAR"
PASTA_SICAR = r"C:\Users\User\Dropbox\Geoinformation\GEOINFO BRASIL\SICAR\BASE_CAR_ESTADOS_05_2026"

# Deixe vazio para TODOS; ou liste siglas (ex.: ["AC"]) para validar.
SOMENTE_ESTES: list[str] = ["SP"]

# Apagar os .shp descompactados ao terminar cada estado (poupa espaço)?
APAGAR_SHP_AO_FIM = True

NATUREZA = "Privado"
COL_COD = "cod_imovel"
PLANOS_TEMATICOS = ["APPS", "RESERVA_LEGAL", "USO_RESTRITO"]
SEL_MANTER = "Representante (manter)"
# =====================================================================

NOME_PARA_UF = {
    "ACRE": "AC", "ALAGOAS": "AL", "AMAPA": "AP", "AMAZONAS": "AM",
    "BAHIA": "BA", "CEARA": "CE", "DISTRITO FEDERAL": "DF",
    "ESPIRITO SANTO": "ES", "GOIAS": "GO", "MARANHAO": "MA",
    "MATO GROSSO": "MT", "MATO GROSSO DO SUL": "MS", "MINAS GERAIS": "MG",
    "PARA": "PA", "PARAIBA": "PB", "PARANA": "PR", "PERNAMBUCO": "PE",
    "PIAUI": "PI", "RIO DE JANEIRO": "RJ", "RIO GRANDE DO NORTE": "RN",
    "RIO GRANDE DO SUL": "RS", "RONDONIA": "RO", "RORAIMA": "RR",
    "SANTA CATARINA": "SC", "SAO PAULO": "SP", "SERGIPE": "SE",
    "TOCANTINS": "TO",
}
UF_PARA_NOME = {uf: nome for nome, uf in NOME_PARA_UF.items()}


def _norm(txt: str) -> str:
    t = unicodedata.normalize("NFKD", str(txt))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.upper().split())


def achar_pasta_estado(uf: str) -> str | None:
    """Acha a pasta do estado no bruto (nome por extenso, tolerante a acento)."""
    alvo = UF_PARA_NOME.get(uf)
    if not alvo:
        return None
    if not os.path.isdir(PASTA_SICAR):
        return None
    for d in os.listdir(PASTA_SICAR):
        if os.path.isdir(os.path.join(PASTA_SICAR, d)) and _norm(d) == alvo:
            return os.path.join(PASTA_SICAR, d)
    return None


def descompactar_plano(pasta_estado: str, plano: str) -> list[str]:
    """Descompacta o(s) .zip do plano (se preciso) e retorna os .shp achados."""
    pasta_plano = os.path.join(pasta_estado, plano)
    if os.path.isdir(pasta_plano):
        shps = sorted(glob.glob(os.path.join(pasta_plano, "*.shp")))
        if shps:
            return shps
        for z in glob.glob(os.path.join(pasta_plano, "*.zip")):
            with zipfile.ZipFile(z) as zf:
                zf.extractall(pasta_plano)
        shps = sorted(glob.glob(os.path.join(pasta_plano, "*.shp")))
        if shps:
            return shps
    z = os.path.join(pasta_estado, plano + ".zip")
    if os.path.exists(z):
        os.makedirs(pasta_plano, exist_ok=True)
        with zipfile.ZipFile(z) as zf:
            zf.extractall(pasta_plano)
        return sorted(glob.glob(os.path.join(pasta_plano, "*.shp")))
    return []


def _apagar_shapefiles(pasta: str) -> None:
    if not os.path.isdir(pasta):
        return
    for shp in glob.glob(os.path.join(pasta, "*.shp")):
        base = os.path.splitext(shp)[0]
        for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qmd", ".fix"):
            f = base + ext
            if os.path.exists(f):
                try:
                    os.remove(f)
                except OSError:
                    pass


def processar_uf(uf: str) -> dict:
    """Recorta as temáticas dos 'manter' de um estado. Lança exceção em erro."""
    gpkg_notif = os.path.join(PASTA_BASE, f"_saida_{uf}",
                              f"{uf}_notificacao_{NATUREZA}.gpkg")
    if not os.path.exists(gpkg_notif):
        raise FileNotFoundError(f"{uf}_notificacao_{NATUREZA}.gpkg não encontrado")

    coer = ler_camada(gpkg_notif, f"{uf}_Notificacao_Coerentes")
    if "selecao_final" not in coer.columns:
        raise KeyError("camada de coerentes sem 'selecao_final'")
    manter = coer[coer["selecao_final"] == SEL_MANTER]
    cods = set(manter[COL_COD].astype(str))
    if not cods:
        return {"uf": uf, "manter": 0, "aviso": "nenhum imóvel 'manter'"}

    pasta_estado = achar_pasta_estado(uf)
    if not pasta_estado:
        raise FileNotFoundError(f"pasta bruta do estado {uf} não encontrada "
                                f"em {PASTA_SICAR}")

    resumo = {"uf": uf, "manter": len(cods)}
    for plano in PLANOS_TEMATICOS:
        shps = descompactar_plano(pasta_estado, plano)
        if not shps:
            resumo[plano] = 0
            continue
        partes = []
        for shp in shps:
            g = ler_camada(shp)
            if COL_COD not in g.columns:
                continue
            # filtra pelos cod_imovel dos 'manter'
            g = g[g[COL_COD].astype(str).isin(cods)]
            # salvaguarda: descarta feições canceladas (não deve haver, mas segura)
            if "des_condic" in g.columns and len(g) > 0:
                fase = g["des_condic"].map(classificar_fase)
                g = g[fase != CANCELADO]
            if len(g) > 0:
                partes.append(g)
        if partes:
            sel = gpd.GeoDataFrame(pd.concat(partes, ignore_index=True),
                                   crs=partes[0].crs)
            escrever_camada(sel, gpkg_notif, plano)
            resumo[plano] = len(sel)
        else:
            resumo[plano] = 0

    if APAGAR_SHP_AO_FIM:
        for plano in PLANOS_TEMATICOS:
            _apagar_shapefiles(os.path.join(pasta_estado, plano))

    return resumo


def main() -> int:
    saidas = sorted(glob.glob(os.path.join(PASTA_BASE, "_saida_*")))
    alvos = []
    for d in saidas:
        uf = os.path.basename(d).replace("_saida_", "").upper()
        if SOMENTE_ESTES and uf not in SOMENTE_ESTES:
            continue
        # só faz sentido para estados que têm o gpkg de notificação
        if os.path.exists(os.path.join(d, f"{uf}_notificacao_{NATUREZA}.gpkg")):
            alvos.append(uf)

    print(f"Estados a processar ({len(alvos)}): {', '.join(alvos)}")
    print(f"Início: {datetime.now():%H:%M:%S}\n")

    sucesso, falhas = [], []
    for uf in alvos:
        print(f"  [{uf}] recortando temáticas...", flush=True)
        try:
            r = processar_uf(uf)
            if r.get("aviso"):
                print(f"       (aviso: {r['aviso']})", flush=True)
            else:
                print(f"       manter={r['manter']} | APPS={r.get('APPS',0)} "
                      f"| RL={r.get('RESERVA_LEGAL',0)} "
                      f"| AUR={r.get('USO_RESTRITO',0)}", flush=True)
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
