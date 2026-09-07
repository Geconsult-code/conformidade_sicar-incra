# -*- coding: utf-8 -*-
"""
correcao_geometrias.py

Regrava (in-place) as geometrias INVALIDAS identificadas no relatorio de
consistencia (relatorio_consistencia_conformidade.py) diretamente nos
.gpkg de Analise_Conformidade, usando make_valid() com fallback buffer(0)
(mesmo padrao ja validado no projeto, incl. no caso patologico do AM).

NAO mexe em geometrias validas (deixa como estao) nem em contagem de
feicoes (so SetFeature na geometria de quem esta invalido, nunca cria ou
remove linha).

Resiliente e retomavel via arquivo de progresso _progresso_correcao.json
(guarda, por camada, o ultimo FID processado). Cada chamada de rodada()
processa um orcamento de tempo (BUDGET_S) e para, pra caber no limite de
tempo da ponte QGIS - rodar de novo continua exatamente de onde parou.
"""

import os
import json
import time

from osgeo import ogr, gdal
import shapely

gdal.UseExceptions()

BASE_ROOT = r"C:\Users\User\Dropbox\#CONSULTANCY\PLANAVEG\GEODATABASE\INCRA-CAR\Analise_Conformidade"
AGREGADO = os.path.join(BASE_ROOT, "_agregado_registros.json")
PROGRESSO = os.path.join(BASE_ROOT, "_progresso_correcao.json")

CHUNK = 25000    # tamanho do bloco de FIDs por leitura/transacao
BUDGET_S = 35    # orcamento de tempo por chamada de rodada()


def carregar_worklist():
    with open(AGREGADO, "r", encoding="utf-8") as f:
        data = json.load(f)
    itens = []
    for r in data["registros"]:
        if r["num_invalidas"] > 0:
            path = os.path.join(BASE_ROOT, f"dados_saída_{r['uf']}", f"{r['uf']}_geopackage", r["arquivo"])
            itens.append({
                "uf": r["uf"], "arquivo": r["arquivo"], "layer": r["layer"], "path": path,
                "num_poligonos": r["num_poligonos"], "num_invalidas_relatorio": r["num_invalidas"],
            })
    itens.sort(key=lambda x: (x["uf"], x["arquivo"], x["layer"]))
    return itens


def carregar_progresso():
    if os.path.isfile(PROGRESSO):
        with open(PROGRESSO, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def salvar_progresso(prog):
    with open(PROGRESSO, "w", encoding="utf-8") as f:
        json.dump(prog, f, ensure_ascii=False, indent=1)


def reparar_geom(ogr_geom):
    wkb = bytes(ogr_geom.ExportToIsoWkb())
    g = shapely.from_wkb(wkb)
    try:
        novo = shapely.make_valid(g)
    except Exception:
        try:
            novo = g.buffer(0)
        except Exception:
            return None
    if novo is None or novo.is_empty:
        return None
    return ogr.CreateGeometryFromWkb(shapely.to_wkb(novo))


def processar_chunk(item, fid_lo, fid_hi):
    ds = ogr.Open(item["path"], update=1)
    lyr = ds.GetLayerByName(item["layer"])
    fidcol = lyr.GetFIDColumn() or "fid"
    lyr.SetAttributeFilter(f'"{fidcol}" >= {fid_lo} AND "{fidcol}" < {fid_hi}')
    lyr.ResetReading()

    n_scan = n_inval = n_fix = n_desc = 0
    lyr.StartTransaction()
    feat = lyr.GetNextFeature()
    while feat is not None:
        n_scan += 1
        geom = feat.GetGeometryRef()
        if geom is not None and not geom.IsValid():
            n_inval += 1
            novo = reparar_geom(geom)
            if novo is not None:
                feat.SetGeometry(novo)
                lyr.SetFeature(feat)
                n_fix += 1
            else:
                n_desc += 1
        feat = lyr.GetNextFeature()
    lyr.CommitTransaction()
    lyr.SetAttributeFilter(None)
    ds = None
    return n_scan, n_inval, n_fix, n_desc


def rodada():
    t0 = time.time()
    worklist = carregar_worklist()
    prog = carregar_progresso()

    log = []
    for item in worklist:
        chave = f"{item['uf']}::{item['arquivo']}::{item['layer']}"
        st = prog.get(chave, {
            "fid_proximo": 0, "concluido": False,
            "total_invalidas": 0, "total_corrigidas": 0, "total_descartadas": 0,
            "total_escaneadas": 0,
        })
        if st["concluido"]:
            continue

        total = item["num_poligonos"]
        while st["fid_proximo"] <= total:
            if time.time() - t0 > BUDGET_S:
                prog[chave] = st
                salvar_progresso(prog)
                log.append(f"[PAUSA orcamento] {chave} em fid={st['fid_proximo']}/{total}")
                print("\n".join(log))
                print(f"\nRODADA parcial: {round(time.time()-t0,1)}s. Rode de novo pra continuar.")
                return False

            lo = st["fid_proximo"]
            hi = lo + CHUNK
            n_scan, n_inval, n_fix, n_desc = processar_chunk(item, lo, hi)
            st["fid_proximo"] = hi
            st["total_escaneadas"] += n_scan
            st["total_invalidas"] += n_inval
            st["total_corrigidas"] += n_fix
            st["total_descartadas"] += n_desc

            if n_scan == 0 and lo > total:
                break

        st["concluido"] = True
        prog[chave] = st
        salvar_progresso(prog)
        log.append(
            f"[OK] {chave}: escaneadas={st['total_escaneadas']} invalidas={st['total_invalidas']} "
            f"corrigidas={st['total_corrigidas']} descartadas={st['total_descartadas']}"
        )

    salvar_progresso(prog)
    print("\n".join(log))
    print(f"\nRODADA completa: TODAS as {len(worklist)} camadas processadas. Tempo: {round(time.time()-t0,1)}s")
    return True


def verificar():
    """Reescaneia todas as camadas do worklist e confere que zero geometrias seguem invalidas."""
    worklist = carregar_worklist()
    problemas = []
    for item in worklist:
        ds = ogr.Open(item["path"])
        lyr = ds.GetLayerByName(item["layer"])
        n_inval = 0
        lyr.ResetReading()
        feat = lyr.GetNextFeature()
        while feat is not None:
            geom = feat.GetGeometryRef()
            if geom is not None and not geom.IsValid():
                n_inval += 1
            feat = lyr.GetNextFeature()
        ds = None
        if n_inval > 0:
            problemas.append({"uf": item["uf"], "arquivo": item["arquivo"], "layer": item["layer"], "restantes": n_inval})
    print(json.dumps(problemas, ensure_ascii=False, indent=1))
    print(f"\nCamadas ainda com invalidas: {len(problemas)} de {len(worklist)}")
    return problemas


if __name__ == "__main__":
    rodada()
