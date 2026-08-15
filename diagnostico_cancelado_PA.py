"""
diagnostico_cancelado_PA.py — descobre ONDE os imóveis 'Cancelado' aparecem
nos GeoPackages de resultado do PA, e com qual des_condic.

Rode (ambiente 'geo' ativo):
    python diagnostico_cancelado_PA.py
"""
import geopandas as gpd
import fiona
from collections import Counter

PASTA = r"C:\Users\User\Dropbox\Geoinformation\GEOINFO BRASIL\SICAR\BASE_CAR_ESTADOS_05_2026\PARA\_saida_PA"
GPKG = PASTA + r"\conformidade_PA_Privado.gpkg"

print(f"Camadas em {GPKG}:")
camadas = fiona.listlayers(GPKG)
for c in camadas:
    print(f"  - {c}")
print()

def resumo_fase(gdf, nome):
    # procura uma coluna de fase (des_condic ou fase)
    col = None
    for cand in ["des_condic", "fase", "DES_CONDIC"]:
        if cand in gdf.columns:
            col = cand; break
    print(f"=== {nome} ({len(gdf)} feições) ===")
    print(f"  colunas: {list(gdf.columns)}")
    if col:
        cont = Counter(gdf[col].astype(str))
        for val, n in cont.most_common():
            flag = "  <<< CANCELADO!" if "cancel" in val.lower() else ""
            print(f"    {col}={val[:50]:<50} {n}{flag}")
    else:
        print("    (sem coluna de fase nesta camada)")
    print()

for cam in camadas:
    try:
        gdf = gpd.read_file(GPKG, layer=cam)
        resumo_fase(gdf, cam)
    except Exception as e:
        print(f"  ! erro lendo {cam}: {e}\n")
