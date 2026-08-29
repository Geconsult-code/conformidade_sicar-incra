"""
listar_camadas_analisados.py — mostra quais camadas existem dentro do
<UF>_analisados.gpkg (para saber se as temáticas APP/RL/AUR dos imóveis
analisados estão disponíveis para recorte).

Rode (ambiente 'geo' ativo):
    python listar_camadas_analisados.py
"""
import os
import glob
import fiona
import geopandas as gpd

BASE = r"C:\Users\User\Dropbox\#CONSULTANCY\PLANAVEG\GEODATABASE\INCRA-CAR"

# inspeciona alguns estados de exemplo
for uf in ["AC", "GO", "MG", "SP"]:
    gpkg = os.path.join(BASE, f"_saida_{uf}", f"{uf}_analisados.gpkg")
    print(f"\n=== {uf}_analisados.gpkg ===")
    if not os.path.exists(gpkg):
        print("  (não existe — estado sem fase Analisado)")
        continue
    try:
        cams = fiona.listlayers(gpkg)
        for c in cams:
            with fiona.open(gpkg, layer=c) as src:
                n = len(src)
            marca = ""
            if c in ("APPS", "RESERVA_LEGAL", "USO_RESTRITO"):
                marca = "   <<< TEMÁTICA (serve para o recorte)"
            print(f"  {c}: {n} feições{marca}")
    except Exception as e:
        print(f"  !! erro: {e}")
