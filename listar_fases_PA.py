"""
listar_fases_PA.py — lista os valores distintos de des_condic e como cada um
está sendo classificado pelo programa. Diagnóstico do bug do "Cancelado".

Rode (ambiente 'geo' ativo):
    python listar_fases_PA.py
"""
import geopandas as gpd
from collections import Counter
from conformidade.fases import classificar_fase

AREA_IMOVEL = r"C:\Users\User\Dropbox\Geoinformation\GEOINFO BRASIL\SICAR\BASE_CAR_ESTADOS_05_2026\PARA\AREA_IMOVEL\AREA_IMOVEL_1.shp"
COL_FASE = "des_condic"

print("Lendo AREA_IMOVEL do PA (pode demorar um pouco)...")
gdf = gpd.read_file(AREA_IMOVEL)
print(f"Total de imóveis: {len(gdf)}\n")

cont = Counter(gdf[COL_FASE].astype(str))
print(f"{'des_condic (texto exato)':<45}{'qtde':>10}   -> classificado como")
print("-" * 85)
for valor, n in cont.most_common():
    fase = classificar_fase(valor)
    print(f"{valor[:44]:<45}{n:>10}   -> {fase}")
