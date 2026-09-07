# -*- coding: utf-8 -*-
"""
relatorio_consistencia_conformidade.py

Verificacao de consistencia + relatorio de area dos geopackages gerados
pela conformidade SICAR x INCRA, apos a renomeacao de arquivos/camadas
feita em Analise_Conformidade (dados_saida_<UF>/<UF>_geopackage/*.gpkg).

O QUE FAZ, por UF e por arquivo .gpkg:
  - confere a projecao de cada camada (deve ser EPSG:4674 - ja validado ao
    vivo via QGIS: as 307 camadas das 27 UFs estao consistentes)
  - verifica validade geometrica de cada poligono (conta invalidas; corrige
    com shapely.make_valid() SO para fins de calculo de area - o .gpkg
    original NAO e alterado, o script e so leitura)
  - conta poligonos e sem-geometria por camada
  - calcula area total por camada, em hectares, via reprojecao equal-area
    EPSG:6933 (mesmo metodo ja validado neste projeto no
    dissolver_car_total.py: diferenca de 0,003% vs area geodesica GRS80
    calculada por pyproj.Geod - usado aqui por ser vetorizado e viavel em
    23 milhoes de feicoes; o metodo ponto-a-ponto via pyproj.Geod seria
    tecnicamente mais "puro" mas levaria horas nesta escala)
  - para as camadas *_incoerentes: area por categoria de des_condic
  - para as camadas *_coerentes: area por categoria cruzando
    des_condic x selecao_final
  - para as demais camadas (APP/RL/AUR selecionados, Imoveis_Analisados,
    Imoveis_Nao_Analisados): so total (sem categorizacao, conforme pedido)

APAGA os JSONs antigos (preparacao_<UF>.json, relatorio_<UF>_Privado.json)
da pasta dados_saida_<UF> e grava um JSON novo por .gpkg, com o MESMO NOME
do .gpkg (extensao .json), na mesma pasta dados_saida_<UF>.

Resiliente por UF/arquivo: se o JSON de saida ja existe, pula (a menos que
a UF esteja em REFAZER). Heartbeat a cada 5 min em heartbeat_relatorio.txt
na raiz de Analise_Conformidade, para acompanhar sem esperar tudo terminar.

Rodar no ambiente conda 'geo' do usuario (mesmo ambiente dos outros
scripts deste projeto):
    conda activate geo
    python relatorio_consistencia_conformidade.py

RECOMENDADO: primeira rodada so com AC (SOMENTE_ESTES ja vem assim por
padrao, mesmo padrao usado nos outros scripts do projeto) para validar
antes do lote completo (23 milhoes de feicoes / 27 estados).
"""

import os
import sys
import json
import time
import glob
import threading

import numpy as np
import geopandas as gpd
import shapely

# --------------------------------------------------------------------------
# CONFIGURACAO
# --------------------------------------------------------------------------

BASE_ROOT = r"C:\Users\User\Dropbox\#CONSULTANCY\PLANAVEG\GEODATABASE\INCRA-CAR\Analise_Conformidade"

EQUAL_AREA_CRS = "EPSG:6933"  # World Cylindrical Equal Area - validado no projeto

UFS = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT",
       "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO"]

FILES_TPL = [
    "{uf}_Conformidade_Imoveis_Nao_Analisados.gpkg",
    "{uf}_Imoveis_Privados_Analisados.gpkg",
    "{uf}_Imoveis_Privados_Nao_Analisados.gpkg",
    "{uf}_Conformidade_Imoveis_Analisados.gpkg",
]

# --- ajuste aqui conforme a rodada ---
SOMENTE_ESTES = ["AM"]   # reprocessar so o AM (2 layers falharam por geometria patologica - ja corrigido)
PULAR = []
REFAZER = ["AM"]          # forca regravar o AM mesmo com JSON existente
# --------------------------------------

HEARTBEAT_INTERVALO_S = 300

_heartbeat_status = {"uf": None, "arquivo": None, "layer": None, "inicio": None}
_heartbeat_stop = False


def _heartbeat_loop(path_hb):
    while not _heartbeat_stop:
        try:
            snap = dict(_heartbeat_status)
            if snap.get("inicio"):
                snap["decorrido_s"] = round(time.time() - snap["inicio"], 1)
            with open(path_hb, "w", encoding="utf-8") as f:
                json.dump(snap, f, ensure_ascii=False, indent=1)
        except Exception:
            pass
        time.sleep(HEARTBEAT_INTERVALO_S)


def listar_layers(path):
    try:
        import pyogrio
        return [row[0] for row in pyogrio.list_layers(path)]
    except Exception:
        import fiona
        return list(fiona.listlayers(path))


def area_ha_equal_area(gdf):
    """Area aproximada (equal-area EPSG:6933), em hectares. Vetorizado."""
    proj = gdf.to_crs(EQUAL_AREA_CRS)
    return proj.geometry.area / 10000.0


def categoria_da_layer(nome_layer):
    if nome_layer.endswith("_incoerentes"):
        return "incoerente"
    if nome_layer.endswith("_coerentes"):
        return "coerente"
    return None


def analisar_layer(gdf, categorizar=None):
    epsg = None
    try:
        epsg = gdf.crs.to_epsg()
    except Exception:
        pass

    n_total = len(gdf)
    arr = np.asarray(gdf.geometry.values, dtype=object)

    missing_mask = shapely.is_missing(arr)
    empty_mask = np.zeros(len(arr), dtype=bool)
    idx_presentes = np.where(~missing_mask)[0]
    if len(idx_presentes) > 0:
        empty_mask[idx_presentes] = shapely.is_empty(arr[idx_presentes])
    vazio_mask = missing_mask | empty_mask
    n_vazio = int(vazio_mask.sum())

    sub = gdf.loc[~vazio_mask].copy()
    n_invalid = 0
    n_descartadas_reparo = 0
    if len(sub) > 0:
        sub_arr = np.asarray(sub.geometry.values, dtype=object)
        invalid_mask = ~shapely.is_valid(sub_arr)
        n_invalid = int(invalid_mask.sum())
        if n_invalid > 0:
            fixed = sub_arr.copy()
            try:
                # caminho rapido: make_valid vetorizado no lote inteiro de invalidas
                fixed[invalid_mask] = shapely.make_valid(sub_arr[invalid_mask])
            except Exception:
                # fallback resiliente geom-a-geom (mesmo padrao do cruzar_vegsec.py,
                # criado pro caso patologico do AM: make_valid pode lancar
                # IllegalArgumentException/mixed-dimension em certas geometrias)
                idx_invalid = np.where(invalid_mask)[0]
                for i in idx_invalid:
                    g = sub_arr[i]
                    novo = None
                    try:
                        novo = shapely.make_valid(g)
                    except Exception:
                        try:
                            novo = g.buffer(0)
                        except Exception:
                            novo = None
                    if novo is None or novo.is_empty:
                        n_descartadas_reparo += 1
                        fixed[i] = None
                    else:
                        fixed[i] = novo
            sub["geometry"] = fixed
            if n_descartadas_reparo > 0:
                descarte_mask = np.array([g is None for g in fixed])
                sub = sub.loc[~descarte_mask].copy()

        if len(sub) > 0:
            sub["_area_ha"] = area_ha_equal_area(sub)
            area_total = float(sub["_area_ha"].sum())
        else:
            area_total = 0.0
    else:
        area_total = 0.0

    result = {
        "epsg": epsg,
        "num_poligonos": int(n_total),
        "num_geometrias_invalidas": n_invalid,
        "num_geometrias_descartadas_no_reparo": n_descartadas_reparo,
        "num_sem_geometria": n_vazio,
        "area_total_ha": round(area_total, 4),
    }

    if categorizar == "incoerente" and len(sub) > 0 and "des_condic" in sub.columns:
        tmp = sub.copy()
        tmp["des_condic"] = tmp["des_condic"].fillna("(vazio)")
        grp = tmp.groupby("des_condic")["_area_ha"].agg(["count", "sum"])
        result["area_por_categoria"] = {
            "campo": "des_condic",
            "categorias": {
                str(k): {"num_poligonos": int(v["count"]), "area_ha": round(float(v["sum"]), 4)}
                for k, v in grp.iterrows()
            },
        }
    elif categorizar == "coerente" and len(sub) > 0 and "des_condic" in sub.columns and "selecao_final" in sub.columns:
        tmp = sub.copy()
        tmp["des_condic"] = tmp["des_condic"].fillna("(vazio)")
        tmp["selecao_final"] = tmp["selecao_final"].fillna("(vazio)")
        grp = tmp.groupby(["des_condic", "selecao_final"])["_area_ha"].agg(["count", "sum"])
        result["area_por_categoria"] = {
            "campos": ["des_condic", "selecao_final"],
            "categorias": {
                f"{k[0]} | {k[1]}": {"num_poligonos": int(v["count"]), "area_ha": round(float(v["sum"]), 4)}
                for k, v in grp.iterrows()
            },
        }

    return result


def processar_arquivo(uf, folder_gpkg, fn):
    path = os.path.join(folder_gpkg, fn)
    if not os.path.isfile(path):
        return None

    layers = listar_layers(path)
    out = {
        "arquivo_geopackage": fn,
        "uf": uf,
        "gerado_em": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "layers": {},
    }
    for lname in layers:
        _heartbeat_status.update({"uf": uf, "arquivo": fn, "layer": lname, "inicio": time.time()})
        t0 = time.time()
        try:
            gdf = gpd.read_file(path, layer=lname)
            cat = categoria_da_layer(lname)
            info = analisar_layer(gdf, categorizar=cat)
        except Exception as e:
            info = {"erro": str(e)}
        out["layers"][lname] = info
        dt = time.time() - t0
        if "erro" in info:
            print(f"  [{uf}] {fn}::{lname} -> ERRO: {info['erro']}")
        else:
            print(f"  [{uf}] {fn}::{lname} -> {info['num_poligonos']} poligonos, "
                  f"{info['num_geometrias_invalidas']} invalidas, "
                  f"{info['num_sem_geometria']} sem geometria, "
                  f"{info['area_total_ha']:.1f} ha ({dt:.1f}s)")
    return out


def apagar_jsons_antigos(folder_saida):
    for pattern in ["preparacao_*.json", "relatorio_*.json"]:
        for p in glob.glob(os.path.join(folder_saida, pattern)):
            try:
                os.remove(p)
                print(f"  apagado: {p}")
            except Exception as e:
                print(f"  ERRO ao apagar {p}: {e}")


def main():
    global _heartbeat_stop

    hb_path = os.path.join(BASE_ROOT, "heartbeat_relatorio.txt")
    hb_thread = threading.Thread(target=_heartbeat_loop, args=(hb_path,), daemon=True)
    hb_thread.start()

    ufs = SOMENTE_ESTES if SOMENTE_ESTES else UFS
    resumo = {}

    for uf in ufs:
        if uf in PULAR:
            continue
        folder_saida = os.path.join(BASE_ROOT, f"dados_saída_{uf}")
        folder_gpkg = os.path.join(folder_saida, f"{uf}_geopackage")
        if not os.path.isdir(folder_gpkg):
            print(f"[{uf}] pasta nao encontrada, pulando")
            continue

        apagar_jsons_antigos(folder_saida)

        t0 = time.time()
        arquivos_ok = []
        for ftpl in FILES_TPL:
            fn = ftpl.format(uf=uf)
            out_json = os.path.join(folder_saida, fn.replace(".gpkg", ".json"))
            if os.path.isfile(out_json) and uf not in REFAZER:
                arquivos_ok.append(fn)
                print(f"[{uf}] {fn} ja tem JSON, pulando (use REFAZER pra forcar)")
                continue
            try:
                res = processar_arquivo(uf, folder_gpkg, fn)
                if res is None:
                    continue
                with open(out_json, "w", encoding="utf-8") as f:
                    json.dump(res, f, ensure_ascii=False, indent=1)
                arquivos_ok.append(fn)
                print(f"[{uf}] gravado {out_json}")
            except Exception as e:
                print(f"[{uf}] ERRO em {fn}: {e}")

        resumo[uf] = {"arquivos": arquivos_ok, "tempo_s": round(time.time() - t0, 1)}
        print(f"[{uf}] concluido em {resumo[uf]['tempo_s']}s")

    _heartbeat_stop = True

    resumo_path = os.path.join(BASE_ROOT, "resumo_relatorio_consistencia.json")
    with open(resumo_path, "w", encoding="utf-8") as f:
        json.dump(resumo, f, ensure_ascii=False, indent=1)
    print("\nRESUMO:")
    print(json.dumps(resumo, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
