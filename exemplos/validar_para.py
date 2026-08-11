"""
validar_para.py — valida o programa contra o resultado de referência do Pará.

Compara, imóvel a imóvel (por ``cod_imovel``), a classificação produzida pelo
programa com a classificação de referência já validada manualmente no QGIS para
o Pará. É a garantia de que a tradução da rotina para código preserva os
números.

COMO USAR
---------
Ajuste os caminhos na seção CONFIG abaixo para apontar:
  - as camadas do SICAR (Em Análise + Aguardando Análise) do PA;
  - a referência INCRA PRIVADA (SIGEF_Privado + SNCI_Privado) do PA;
  - o GeoPackage de referência com as camadas coerentes/incoerentes privadas já
    classificadas (o resultado validado no QGIS).

Depois:
    python exemplos/validar_para.py

O script imprime a matriz de concordância do ``motivo`` e destaca divergências.
Uma concordância de 100% (ou muito próxima, a menos de diferenças numéricas de
borda) confirma a fidelidade da tradução.

OBSERVAÇÃO
----------
Pequenas divergências em imóveis exatamente no limiar (ex.: containment = 0,990)
podem ocorrer por diferenças de arredondamento entre o motor geométrico do QGIS
(GEOS) e o do Shapely (também GEOS, mas versões possivelmente distintas). O
esperado é que sejam pouquíssimos casos e sempre em imóveis de fronteira.
"""

from __future__ import annotations

import sys
from collections import Counter

import geopandas as gpd

from conformidade.io_dados import ler_camada, concatenar
from conformidade.pipeline import (
    ConfigPipeline, montar_referencia, classificar_camada_sicar,
)

# ============================ CONFIG ============================
# Ajuste estes caminhos para os seus arquivos do Pará.
SICAR = [
    "dados_PA/SICAR_Para_Em_Analise.shp",
    "dados_PA/SICAR_Para_Aguardando_Analise.shp",
]
SIGEF_PRIVADO = "dados_PA/SIGEF_Para_Privado.shp"
SNCI_PRIVADO = "dados_PA/SNCI_Para_Privado.shp"

# GeoPackage de referência (resultado validado no QGIS) e nomes das camadas
# com os imóveis já classificados (contendo cod_imovel e motivo).
REF_GPKG = "dados_PA/INCRA-CAR_resultado_v2.gpkg"
REF_CAMADAS_COERENTES = [
    "SICAR_Para_Em_Analise_Privado_Coerentes",
    "SICAR_Para_Aguardando_Analise_Privado_Coerentes",
]
REF_CAMADAS_INCOERENTES = [
    "SICAR_Para_Em_Analise_Privado_Incoerentes",
    "SICAR_Para_Aguardando_Analise_Privado_Incoerentes",
]
COL_COD = "cod_imovel"
# Use os mesmos limiares da rotina de referência.
CFG = ConfigPipeline(limiar_sobreposicao=0.70, subdividir=True)
# ===============================================================


def carregar_referencia() -> dict:
    """Lê o resultado de referência: {cod_imovel: motivo}."""
    ref = {}
    for cam in REF_CAMADAS_COERENTES + REF_CAMADAS_INCOERENTES:
        gdf = ler_camada(REF_GPKG, cam)
        for _, row in gdf.iterrows():
            ref[row[COL_COD]] = row["motivo"]
    return ref


def main() -> int:
    print("Lendo bases do Pará...", file=sys.stderr)
    sicar = concatenar([ler_camada(c) for c in SICAR])
    referencia = montar_referencia([
        ler_camada(SIGEF_PRIVADO), ler_camada(SNCI_PRIVADO),
    ])

    print(f"Classificando {len(sicar)} imóveis...", file=sys.stderr)
    res = classificar_camada_sicar(sicar, referencia, CFG, natureza="Privado")
    todos = gpd.pd.concat([res.coerentes, res.incoerentes], ignore_index=True)
    calc = {row[COL_COD]: row["motivo"] for _, row in todos.iterrows()}

    print("Carregando resultado de referência (QGIS)...", file=sys.stderr)
    ref = carregar_referencia()

    # ----- Comparação -----
    comuns = set(calc) & set(ref)
    so_calc = set(calc) - set(ref)
    so_ref = set(ref) - set(calc)

    iguais = sum(1 for c in comuns if calc[c] == ref[c])
    difer = [c for c in comuns if calc[c] != ref[c]]

    print("\n=== VALIDAÇÃO PARÁ (motivo) ===")
    print(f"Imóveis no cálculo: {len(calc)}")
    print(f"Imóveis na referência: {len(ref)}")
    print(f"Comparáveis (em ambos): {len(comuns)}")
    print(f"  concordantes: {iguais} ({100*iguais/max(len(comuns),1):.3f}%)")
    print(f"  divergentes:  {len(difer)}")
    if so_calc:
        print(f"  só no cálculo: {len(so_calc)}")
    if so_ref:
        print(f"  só na referência: {len(so_ref)}")

    if difer:
        print("\n--- Matriz de divergências (referência -> cálculo) ---")
        mat = Counter((ref[c], calc[c]) for c in difer)
        for (r_mot, c_mot), n in mat.most_common():
            print(f"  {r_mot:24} -> {c_mot:24} : {n}")
        print("\nExemplos (até 10):")
        for c in difer[:10]:
            print(f"  {c}: ref={ref[c]} calc={calc[c]}")

    ok = (len(difer) == 0 and not so_calc and not so_ref)
    print(f"\nResultado: {'IDÊNTICO ✓' if ok else 'há divergências — investigar'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
