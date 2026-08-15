"""
sensibilidade_analisados_PA.py — tabela de sensibilidade do limiar de
sobreposição com os imóveis Analisado, usando o frac_analisado JÁ GRAVADO no
resultado atual (não reprocessa nada).

Mostra, para cada limiar (5%, 10%, ..., 90%), quantos imóveis seriam mantidos
vs. eliminados por sobreposição com um analisado — ajudando a escolher o corte.

Rode (ambiente 'geo' ativo):
    python sensibilidade_analisados_PA.py
"""
import geopandas as gpd

PASTA = r"C:\Users\User\Dropbox\Geoinformation\GEOINFO BRASIL\SICAR\BASE_CAR_ESTADOS_05_2026\PARA\_saida_PA"
GPKG = PASTA + r"\conformidade_PA_Privado.gpkg"
CAMADA = "PA_Privado_Coerentes"

print(f"Lendo {CAMADA}...")
g = gpd.read_file(GPKG, layer=CAMADA)

# Considera só os que passaram na sobreposição interna (representantes):
# esses são os candidatos que o filtro vs Analisado decide manter ou não.
rep = g[g["classe_espacial"] == "representante"].copy()
print(f"Representantes (candidatos ao filtro vs Analisado): {len(rep)}\n")

fa = rep["frac_analisado"].fillna(0.0)

print("Limiar vs Analisado  |  Eliminados (sobrepoe)  |  Mantidos  |  % mantido")
print("-" * 72)
for limiar in [0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90]:
    elim = int((fa >= limiar).sum())
    mant = len(rep) - elim
    pct = 100 * mant / len(rep) if len(rep) else 0
    marca = "  <-- atual (0.10)" if abs(limiar - 0.10) < 1e-9 else ""
    marca = "  <-- sugerido (0.30)" if abs(limiar - 0.30) < 1e-9 else marca
    print(f"      {int(limiar*100):>3}%           |      {elim:>8}          |  {mant:>8}  |  {pct:>5.1f}%{marca}")

# Distribuição de quão "de fronteira" são as sobreposições atuais (>=10%)
print("\n--- Entre os eliminados hoje (frac_analisado >= 0.10), como se distribuem? ---")
elim_hoje = fa[fa >= 0.10]
faixas = [(0.10,0.20),(0.20,0.30),(0.30,0.50),(0.50,0.70),(0.70,1.01)]
for lo, hi in faixas:
    n = int(((elim_hoje >= lo) & (elim_hoje < hi)).sum())
    print(f"  {int(lo*100)}%–{int(hi*100)}%: {n}")
print(f"\nTotal eliminados hoje (>=10%): {int((fa>=0.10).sum())}")
