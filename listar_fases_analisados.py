"""
listar_fases_analisados.py — lista os valores de des_condic presentes no
<UF>_analisados.gpkg de um estado, para identificar a grafia EXATA da fase
"analisado, com pendências".

Rode (ambiente 'geo' ativo):
    python listar_fases_analisados.py
"""
import os
import glob
from collections import Counter

import geopandas as gpd
import fiona

# pasta onde estão as pastas _saida_<UF>
BASE = r"C:\Users\User\Dropbox\#CONSULTANCY\PLANAVEG\GEODATABASE\INCRA-CAR"

# estado de exemplo para inspecionar (troque se quiser outro)
UF = "AC"

gpkg = os.path.join(BASE, f"_saida_{UF}", f"{UF}_analisados.gpkg")
print(f"Arquivo: {gpkg}")
if not os.path.exists(gpkg):
    print("  !! não encontrado. Estados sem fase 'Analisado' não têm este arquivo.")
    # tenta achar qualquer _analisados.gpkg como exemplo
    cands = glob.glob(os.path.join(BASE, "_saida_*", "*_analisados.gpkg"))
    if cands:
        gpkg = cands[0]
        print(f"  usando outro como exemplo: {gpkg}")
    else:
        raise SystemExit("nenhum _analisados.gpkg encontrado")

# a camada de imóveis costuma se chamar AREA_IMOVEL
camadas = fiona.listlayers(gpkg)
print(f"camadas: {camadas}")
cam = "AREA_IMOVEL" if "AREA_IMOVEL" in camadas else camadas[0]

g = gpd.read_file(gpkg, layer=cam)
print(f"\ncamada '{cam}': {len(g)} imóveis")
if "des_condic" not in g.columns:
    print(f"  !! sem coluna des_condic. Colunas: {list(g.columns)}")
    raise SystemExit

print(f"\n{'des_condic (texto EXATO)':<55}{'qtde':>10}")
print("-" * 66)
for val, n in Counter(g["des_condic"].astype(str)).most_common():
    # destaca as que contêm 'pend'
    marca = "  <<< contém 'pend'" if "pend" in str(val).lower() else ""
    print(f"{val[:54]:<55}{n:>10}{marca}")
