"""
rodar_validacao_pa.py — valida o programa Python contra o resultado do QGIS (PA).

Este script já vem com os caminhos e nomes de camada preenchidos para o teste do
Pará. Basta rodá-lo (com o ambiente 'geo' ativo):

    python rodar_validacao_pa.py

Ele:
  1. lê as camadas de ENTRADA do PA_teste.gpkg (sicar_em, sicar_agu,
     sigef_privado, snci_privado);
  2. classifica a coerência com o programa (etapa de coerência + subdivisão);
  3. lê o resultado de referência (QGIS) do INCRA-CAR_resultado_v2.gpkg;
  4. compara o campo 'motivo' imóvel a imóvel e imprime a concordância.

Nada é gravado; é só leitura e comparação.
"""

from __future__ import annotations

import sys
from collections import Counter

import geopandas as gpd

from conformidade.io_dados import ler_camada, concatenar
from conformidade.pipeline import (
    ConfigPipeline, montar_referencia, classificar_camada_sicar,
)

# ======================= CONFIG (já preenchido) =======================
PASTA = r"C:\Users\User\Dropbox\#CONSULTANCY\PLANAVEG\GEODATABASE\INCRA-CAR"

ENTRADA_GPKG = PASTA + r"\PA_teste.gpkg"
SICAR_CAMADAS = ["sicar_em", "sicar_agu"]
SIGEF_CAMADA = "sigef_privado"
SNCI_CAMADA = "snci_privado"

REF_GPKG = PASTA + r"\INCRA-CAR_resultado_v2.gpkg"
REF_CAMADAS_COERENTES = [
    "SICAR_Para_Em_Analise_Privado_Coerentes",
    "SICAR_Para_Aguardando_Analise_Privado_Coerentes",
]
REF_CAMADAS_INCOERENTES = [
    "SICAR_Para_Em_Analise_Privado_Incoerentes",
    "SICAR_Para_Aguardando_Analise_Privado_Incoerentes",
]

COL_COD = "cod_imovel"
# Mesmos limiares/critérios da rotina validada no QGIS.
CFG = ConfigPipeline(limiar_sobreposicao=0.10, subdividir=True)
# ======================================================================


def carregar_referencia() -> dict:
    """Lê o resultado de referência do QGIS: {cod_imovel: motivo}."""
    ref = {}
    for cam in REF_CAMADAS_COERENTES + REF_CAMADAS_INCOERENTES:
        gdf = ler_camada(REF_GPKG, cam)
        if COL_COD not in gdf.columns or "motivo" not in gdf.columns:
            print(f"  ! camada '{cam}': falta '{COL_COD}' ou 'motivo' "
                  f"(colunas: {list(gdf.columns)})", file=sys.stderr)
            continue
        for _, row in gdf.iterrows():
            ref[row[COL_COD]] = row["motivo"]
    return ref


def main() -> int:
    print("Lendo camadas de entrada do PA_teste.gpkg...", file=sys.stderr)
    sicar = concatenar([ler_camada(ENTRADA_GPKG, c) for c in SICAR_CAMADAS])
    referencia = montar_referencia([
        ler_camada(ENTRADA_GPKG, SIGEF_CAMADA),
        ler_camada(ENTRADA_GPKG, SNCI_CAMADA),
    ])
    print(f"  SICAR (trabalho): {len(sicar)} imóveis | "
          f"INCRA privado: {len(referencia.geoms)} parcelas", file=sys.stderr)

    print("Classificando coerência (pode levar alguns minutos)...", file=sys.stderr)
    res = classificar_camada_sicar(sicar, referencia, CFG, natureza="Privado")
    todos = gpd.pd.concat([res.coerentes, res.incoerentes], ignore_index=True)
    calc = {row[COL_COD]: row["motivo"] for _, row in todos.iterrows()}

    print("Lendo resultado de referência do QGIS...", file=sys.stderr)
    ref = carregar_referencia()

    # -------- Comparação imóvel a imóvel --------
    comuns = set(calc) & set(ref)
    so_calc = set(calc) - set(ref)
    so_ref = set(ref) - set(calc)
    iguais = sum(1 for c in comuns if calc[c] == ref[c])
    difer = [c for c in comuns if calc[c] != ref[c]]

    print("\n=========== VALIDAÇÃO PARÁ (campo 'motivo') ===========")
    print(f"Imóveis classificados pelo programa: {len(calc)}")
    print(f"Imóveis no resultado do QGIS:        {len(ref)}")
    print(f"Comparáveis (presentes em ambos):    {len(comuns)}")
    pct = 100 * iguais / max(len(comuns), 1)
    print(f"  CONCORDANTES: {iguais}  ({pct:.3f}%)")
    print(f"  divergentes:  {len(difer)}")
    if so_calc:
        print(f"  só no programa (não no QGIS): {len(so_calc)}")
    if so_ref:
        print(f"  só no QGIS (não no programa): {len(so_ref)}")

    # Contagem por motivo (programa), para visão geral.
    print("\n--- Distribuição por motivo (programa) ---")
    for mot, n in Counter(calc.values()).most_common():
        print(f"  {mot:28} {n}")

    if difer:
        print("\n--- Onde divergiu (QGIS -> programa) ---")
        mat = Counter((ref[c], calc[c]) for c in difer)
        for (r_mot, c_mot), n in mat.most_common():
            print(f"  {r_mot:26} -> {c_mot:26} : {n}")
        print("\nExemplos de códigos divergentes (até 10):")
        for c in list(difer)[:10]:
            print(f"  {c}: QGIS={ref[c]}  programa={calc[c]}")

    print("\n" + ("=" * 55))
    if not difer and not so_calc and not so_ref:
        print("RESULTADO: IDÊNTICO — o programa reproduz o QGIS. ✓")
    else:
        print("RESULTADO: há diferenças — ver acima. (pode ser normal em "
              "imóveis de fronteira; investigamos juntos)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
