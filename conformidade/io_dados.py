"""
io_dados.py — leitura, escrita e verificação de conservação.

Responsável por:
  - ler camadas vetoriais (shapefile, GeoPackage, GeoJSON...) via GeoPandas;
  - harmonizar o CRS para EPSG:4674 (SIRGAS2000);
  - escrever GeoPackages compactos e portáveis (compatíveis com ArcGIS);
  - verificar a "conservação" (a soma das saídas bate com a entrada).

Observações de robustez aprendidas em campo:
  - GeoPackage/SQLite acima de ~2 GB pode ser rejeitado por leitores rígidos
    (ArcGIS). Quando uma camada de saída passar desse limite, o programa avisa
    e sugere dividir (ver :func:`avisar_se_grande`).
  - Não misturamos dados de fontes distintas sem registrar a proveniência.
"""

from __future__ import annotations

import os
import warnings
from typing import Iterable

import geopandas as gpd

from .geometria import CRS_TRABALHO

LIMITE_GPKG_BYTES = 2_000_000_000  # ~2 GB: zona de risco para alguns leitores


def ler_camada(caminho: str, camada: str | None = None) -> gpd.GeoDataFrame:
    """Lê uma camada vetorial e harmoniza o CRS para EPSG:4674.

    ``caminho`` pode ser um shapefile (.shp), GeoPackage (.gpkg, com
    ``camada``), GeoJSON etc. Se o CRS de origem for diferente de EPSG:4674,
    a geometria é reprojetada.
    """
    gdf = gpd.read_file(caminho, layer=camada) if camada else gpd.read_file(caminho)
    if gdf.crs is None:
        warnings.warn(
            f"{caminho}: CRS ausente; assumindo {CRS_TRABALHO}. "
            "Verifique se os dados estão mesmo em SIRGAS2000."
        )
        gdf = gdf.set_crs(CRS_TRABALHO, allow_override=True)
    elif gdf.crs.to_epsg() != 4674:
        gdf = gdf.to_crs(CRS_TRABALHO)
    return gdf


def concatenar(gdfs: Iterable[gpd.GeoDataFrame]) -> gpd.GeoDataFrame:
    """Concatena GeoDataFrames preservando o CRS de trabalho."""
    import pandas as pd
    gdfs = [g for g in gdfs if g is not None and len(g) > 0]
    if not gdfs:
        return gpd.GeoDataFrame(geometry=[], crs=CRS_TRABALHO)
    out = pd.concat(gdfs, ignore_index=True)
    return gpd.GeoDataFrame(out, geometry="geometry", crs=CRS_TRABALHO)


def escrever_camada(gdf: gpd.GeoDataFrame, caminho_gpkg: str, camada: str) -> None:
    """Escreve ``gdf`` como uma camada de GeoPackage e avisa se ficar grande."""
    os.makedirs(os.path.dirname(os.path.abspath(caminho_gpkg)), exist_ok=True)
    gdf.to_file(caminho_gpkg, layer=camada, driver="GPKG")
    avisar_se_grande(caminho_gpkg, camada)


def avisar_se_grande(caminho_gpkg: str, camada: str) -> None:
    """Emite aviso se o arquivo passar do limite de risco (~2 GB)."""
    try:
        tam = os.path.getsize(caminho_gpkg)
    except OSError:
        return
    if tam >= LIMITE_GPKG_BYTES:
        warnings.warn(
            f"{caminho_gpkg} ({tam/1e9:.2f} GB) passou de ~2 GB após gravar "
            f"'{camada}'. Leitores rígidos (ArcGIS) podem recusá-lo. "
            "Considere dividir por tipo/origem."
        )


def verificar_conservacao(total_entrada: int, *partes: int) -> tuple[bool, int]:
    """Confere se a soma das partes é igual ao total de entrada.

    Retorna ``(ok, soma)``. Use para garantir que a classificação não perdeu
    nem duplicou imóveis.
    """
    soma = sum(partes)
    return (soma == total_entrada, soma)
