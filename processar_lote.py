r"""
processar_lote.py — processa TODOS os estados do Brasil em sequência.

Ferramenta de atualização: sempre que novos dados do SICAR e/ou INCRA forem
disponibilizados, basta atualizar as pastas de origem e rodar este script para
reprocessar o país inteiro (ou os estados que você escolher).

Para cada estado dentro de ``PASTA_SICAR``, o script:
  1. descompacta os .zip dos planos usados (AREA_IMOVEL, APPS, RESERVA_LEGAL,
     USO_RESTRITO), pulando os que já estiverem descompactados;
  2. junta os pedaços fatiados (AREA_IMOVEL_1..N, APPS_1..N, ...);
  3. localiza o INCRA privado do estado (SIGEF_Privado_<UF>, SNCI_Privado_<UF>);
  4. roda ``conformidade preparar`` e ``conformidade analisar`` (limiar 0,30 já
     é o padrão), gravando o resultado numa subpasta ``_saida_<UF>`` do estado;
  5. opcionalmente apaga os .shp descompactados para poupar espaço.

Se um estado falhar, o script anota o erro e SEGUE para o próximo; ao final
lista os que deram certo e os que falharam.

COMO USAR
---------
1. Coloque os dados nas pastas de origem (ver CONFIG): o SICAR bruto de cada
   estado em PASTA_SICAR\<ESTADO>\ (com os .zip dos planos), e o INCRA por UF
   (SIGEF_Privado_<UF>.shp / SNCI_Privado_<UF>.shp) em PASTA_INCRA — este último
   pode ser gerado das bases nacionais com o utilitário separar_incra_por_uf.py.
2. Confira os caminhos na seção CONFIG.
3. Com o ambiente 'geo' ativo:
       python processar_lote.py

Por padrão processa TODOS os estados encontrados. Para refazer só alguns,
preencha SOMENTE_ESTES (ex.: ["SP", "TO"]). Para pular alguns, use PULAR.
Reprocessar sobrescreve os resultados anteriores em cada _saida_<UF>.

NOTA: zips muito grandes do SICAR podem, ocasionalmente, não abrir pelo Python
(formato ZIP64 ou download corrompido). Nesse caso, extraia o .zip do plano à
mão na respectiva subpasta — o script detecta os .shp já descompactados e segue.
"""

from __future__ import annotations

import os
import sys
import glob
import shutil
import zipfile
import subprocess
import unicodedata
import tempfile
from datetime import datetime

import geopandas as gpd

# =============================== CONFIG ===============================
PASTA_SICAR = r"C:\Users\User\Dropbox\Geoinformation\GEOINFO BRASIL\SICAR\BASE_CAR_ESTADOS_05_2026"
PASTA_INCRA = r"C:\Users\User\Dropbox\Geoinformation\GEOINFO BRASIL\INCRA"

# Estados a PULAR nesta execução (opcional). Deixe vazio para processar TODOS.
# Útil quando você já reprocessou alguns e quer refazer só os demais.
PULAR: list[str] = []
# Para rodar SÓ alguns estados, liste as siglas aqui (senão deixe vazio = todos).
SOMENTE_ESTES: list[str] = []

# Apagar os .shp descompactados ao terminar cada estado (poupa espaço)?
APAGAR_SHP_AO_FIM = True

# Natureza da referência INCRA usada nesta rodada.
NATUREZA = "Privado"

# Planos usados na análise. AREA_IMOVEL é obrigatório; os 3 temáticos entram
# no recorte final. Nomes = nomes das subpastas/zip dentro da pasta do estado.
PLANO_AREA = "AREA_IMOVEL"
PLANOS_TEMATICOS = ["APPS", "RESERVA_LEGAL", "USO_RESTRITO"]
# =====================================================================


# Mapa nome-do-estado (por extenso, normalizado) -> sigla UF.
NOME_PARA_UF = {
    "ACRE": "AC", "ALAGOAS": "AL", "AMAPA": "AP", "AMAZONAS": "AM",
    "BAHIA": "BA", "CEARA": "CE", "DISTRITO FEDERAL": "DF",
    "ESPIRITO SANTO": "ES", "GOIAS": "GO", "MARANHAO": "MA",
    "MATO GROSSO": "MT", "MATO GROSSO DO SUL": "MS", "MINAS GERAIS": "MG",
    "PARA": "PA", "PARAIBA": "PB", "PARANA": "PR", "PERNAMBUCO": "PE",
    "PIAUI": "PI", "RIO DE JANEIRO": "RJ", "RIO GRANDE DO NORTE": "RN",
    "RIO GRANDE DO SUL": "RS", "RONDONIA": "RO", "RORAIMA": "RR",
    "SANTA CATARINA": "SC", "SAO PAULO": "SP", "SERGIPE": "SE",
    "TOCANTINS": "TO",
}


def _norm(txt: str) -> str:
    """Maiúsculas, sem acento, espaços colapsados — para casar nomes de pasta."""
    t = unicodedata.normalize("NFKD", txt)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.upper().split())


def uf_da_pasta(nome_pasta: str) -> str | None:
    """Descobre a sigla UF a partir do nome da pasta do estado."""
    return NOME_PARA_UF.get(_norm(nome_pasta))


def descompactar_plano(pasta_estado: str, plano: str) -> list[str]:
    """Descompacta o(s) .zip do plano (se preciso) e retorna os .shp achados.

    Procura tanto uma subpasta com o nome do plano quanto um <plano>.zip solto.
    Se os .shp já existirem, não descompacta de novo.
    """
    pasta_plano = os.path.join(pasta_estado, plano)
    # 1) já existe subpasta com .shp dentro?
    if os.path.isdir(pasta_plano):
        shps = sorted(glob.glob(os.path.join(pasta_plano, "*.shp")))
        if shps:
            return shps
        # subpasta existe mas sem shp: procurar zip dentro dela
        for z in glob.glob(os.path.join(pasta_plano, "*.zip")):
            with zipfile.ZipFile(z) as zf:
                zf.extractall(pasta_plano)
        shps = sorted(glob.glob(os.path.join(pasta_plano, "*.shp")))
        if shps:
            return shps
    # 2) zip solto na pasta do estado (ex.: APPS.zip)
    z = os.path.join(pasta_estado, plano + ".zip")
    if os.path.exists(z):
        os.makedirs(pasta_plano, exist_ok=True)
        with zipfile.ZipFile(z) as zf:
            zf.extractall(pasta_plano)
        return sorted(glob.glob(os.path.join(pasta_plano, "*.shp")))
    return []


def juntar_pedacos(shps: list[str], destino: str) -> str:
    """Se houver vários .shp (plano fatiado), concatena num único destino.

    Retorna o caminho do arquivo único (o próprio, se já era um só).
    """
    if len(shps) == 1:
        return shps[0]
    partes = [gpd.read_file(s) for s in shps]
    junto = gpd.GeoDataFrame(
        gpd.pd.concat(partes, ignore_index=True), crs=partes[0].crs)
    junto.to_file(destino)
    return destino


def achar_incra(uf: str) -> tuple[str | None, str | None]:
    """Localiza SIGEF_Privado_<UF>.shp e SNCI_Privado_<UF>.shp."""
    sigef = os.path.join(PASTA_INCRA, f"SIGEF_Privado_{uf}.shp")
    snci = os.path.join(PASTA_INCRA, f"SNCI_Privado_{uf}.shp")
    return (sigef if os.path.exists(sigef) else None,
            snci if os.path.exists(snci) else None)


def processar_estado(nome_pasta: str) -> None:
    """Roda o fluxo completo para um estado. Lança exceção em caso de erro."""
    pasta_estado = os.path.join(PASTA_SICAR, nome_pasta)
    uf = uf_da_pasta(nome_pasta)
    if not uf:
        raise ValueError(f"não reconheci a UF da pasta '{nome_pasta}'")

    print(f"\n{'='*60}\n  {nome_pasta}  (UF={uf})\n{'='*60}", file=sys.stderr)
    saida = os.path.join(pasta_estado, f"_saida_{uf}")
    os.makedirs(saida, exist_ok=True)

    criados_tmp: list[str] = []  # arquivos que podemos apagar no fim

    # ---- AREA_IMOVEL (obrigatório) ----
    print("  [descompactar] AREA_IMOVEL...", file=sys.stderr)
    shps_area = descompactar_plano(pasta_estado, PLANO_AREA)
    if not shps_area:
        raise FileNotFoundError(f"AREA_IMOVEL não encontrado em {pasta_estado}")
    area_unico = juntar_pedacos(
        shps_area, os.path.join(saida, f"_area_imovel_{uf}.shp"))
    if area_unico != shps_area[0]:
        criados_tmp.append(area_unico)

    # ---- INCRA ----
    sigef, snci = achar_incra(uf)
    if not sigef and not snci:
        raise FileNotFoundError(
            f"INCRA de {uf} não encontrado (SIGEF/SNCI_Privado_{uf}.shp)")

    # ---- planos temáticos (aceitam vários pedaços; passamos a lista) ----
    tematicos: dict[str, list[str]] = {}
    for plano in PLANOS_TEMATICOS:
        print(f"  [descompactar] {plano}...", file=sys.stderr)
        shps = descompactar_plano(pasta_estado, plano)
        if shps:
            tematicos[plano] = shps

    # ---- PREPARAR ----
    print("  [preparar] separando por fase...", file=sys.stderr)
    cmd_prep = [sys.executable, "-m", "conformidade.cli", "preparar",
                "--area-imovel", area_unico, "--uf", uf, "--saida", saida]
    _run(cmd_prep, f"preparar {uf}")

    # ---- ANALISAR ----
    print("  [analisar] classificando + recorte...", file=sys.stderr)
    gpkg_analisados = os.path.join(saida, f"{uf}_analisados.gpkg")
    cmd_ana = [sys.executable, "-m", "conformidade.cli", "analisar",
               "--sicar", os.path.join(saida, f"{uf}_trabalho.gpkg"),
               "--sicar-camada", "AREA_IMOVEL",
               "--natureza", NATUREZA,
               "--uf", uf, "--saida", saida]
    # o pacote de analisados só existe se houver imóveis na fase Analisado
    if os.path.exists(gpkg_analisados):
        cmd_ana += ["--analisados", gpkg_analisados,
                    "--analisados-camada", "AREA_IMOVEL"]
    if sigef:
        cmd_ana += ["--sigef", sigef]
    if snci:
        cmd_ana += ["--snci", snci]
    for plano, chave in [("APPS", "--apps"), ("RESERVA_LEGAL", "--reserva-legal"),
                         ("USO_RESTRITO", "--uso-restrito")]:
        if plano in tematicos:
            cmd_ana += [chave] + tematicos[plano]
    _run(cmd_ana, f"analisar {uf}")

    # ---- limpeza dos .shp descompactados ----
    if APAGAR_SHP_AO_FIM:
        print("  [limpeza] apagando .shp descompactados...", file=sys.stderr)
        for plano in [PLANO_AREA] + PLANOS_TEMATICOS:
            _apagar_shapefiles(os.path.join(pasta_estado, plano))
        for tmp in criados_tmp:
            _apagar_shapefile_unico(tmp)

    print(f"  OK: resultado em {saida}", file=sys.stderr)


def _run(cmd: list[str], rotulo: str) -> None:
    """Executa um subcomando e mostra o resumo; lança erro se falhar."""
    r = subprocess.run(cmd, capture_output=True, text=True)
    # mostra só as últimas linhas do resumo (stderr do CLI traz o progresso)
    saida = (r.stderr or "") + (r.stdout or "")
    for linha in saida.strip().splitlines()[-12:]:
        print("    " + linha, file=sys.stderr)
    if r.returncode != 0:
        raise RuntimeError(f"{rotulo} falhou (código {r.returncode})")


def _apagar_shapefiles(pasta: str) -> None:
    """Apaga todos os shapefiles (e arquivos irmãos) de uma pasta."""
    if not os.path.isdir(pasta):
        return
    for shp in glob.glob(os.path.join(pasta, "*.shp")):
        _apagar_shapefile_unico(shp)


def _apagar_shapefile_unico(shp: str) -> None:
    base = os.path.splitext(shp)[0]
    for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qmd", ".fix"):
        f = base + ext
        if os.path.exists(f):
            try:
                os.remove(f)
            except OSError:
                pass


def main() -> int:
    if not os.path.isdir(PASTA_SICAR):
        print(f"Pasta do SICAR não encontrada: {PASTA_SICAR}", file=sys.stderr)
        return 1

    # Descobre os estados (subpastas da pasta do SICAR).
    pastas = [d for d in sorted(os.listdir(PASTA_SICAR))
              if os.path.isdir(os.path.join(PASTA_SICAR, d))]

    alvos = []
    for nome in pastas:
        uf = uf_da_pasta(nome)
        if not uf:
            continue  # pasta que não é estado (ex.: uma pasta de saída avulsa)
        if uf in PULAR:
            continue
        if SOMENTE_ESTES and uf not in SOMENTE_ESTES:
            continue
        alvos.append(nome)

    print(f"Estados a processar ({len(alvos)}): "
          f"{', '.join(uf_da_pasta(n) for n in alvos)}", file=sys.stderr)
    print(f"Início: {datetime.now():%H:%M:%S}\n", file=sys.stderr)

    sucesso, falhas = [], []
    for nome in alvos:
        uf = uf_da_pasta(nome)
        try:
            processar_estado(nome)
            sucesso.append(uf)
        except Exception as e:
            print(f"  !! ERRO em {uf}: {e}", file=sys.stderr)
            falhas.append((uf, str(e)))

    # ---- Relatório final ----
    print(f"\n{'#'*60}\n  RELATÓRIO FINAL  ({datetime.now():%H:%M:%S})\n{'#'*60}",
          file=sys.stderr)
    print(f"Sucesso ({len(sucesso)}): {', '.join(sucesso) or '—'}",
          file=sys.stderr)
    if falhas:
        print(f"\nFalharam ({len(falhas)}):", file=sys.stderr)
        for uf, msg in falhas:
            print(f"  {uf}: {msg}", file=sys.stderr)
    else:
        print("\nNenhuma falha. 🎉", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
