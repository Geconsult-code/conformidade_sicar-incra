"""
cli.py — interface de linha de comando da análise de conformidade SICAR × INCRA.

Uso típico (um estado, natureza privada, pipeline completa)::

    python -m conformidade.cli \\
        --sicar SICAR_Em.shp SICAR_Aguardando.shp \\
        --sigef SIGEF_Privado.shp --snci SNCI_Privado.shp \\
        --natureza Privado \\
        --tematicas APP.shp RL.shp AUR.shp \\
        --limiar-sobreposicao 0.70 \\
        --saida resultado_PA/ --uf PA

As etapas são modulares (veja ``--ate`` e as flags ``--sem-*``). A cada etapa,
o programa confere a CONSERVAÇÃO (soma das saídas == entrada) e avisa se algum
GeoPackage passar de ~2 GB.

Este módulo apenas: (1) lê arquivos, (2) chama a biblioteca ``conformidade``,
(3) grava GeoPackages e um relatório. Toda a lógica científica está na
biblioteca.
"""

from __future__ import annotations

import argparse
import os
import sys
import json
from datetime import datetime, timezone

from .io_dados import ler_camada, concatenar, escrever_camada
from .classificacao import Limiares
from .subdivisao import ParametrosSubdivisao
from .pipeline import (
    ConfigPipeline, montar_referencia, classificar_camada_sicar,
    aplicar_sobreposicao,
)
from .recorte import filtrar_tematicas


ETAPAS = ["coerencia", "sobreposicao", "recorte"]


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="conformidade",
        description="Classificação de coerência SICAR × INCRA com filtro de "
                    "sobreposição espacial e recorte temático (APP/RL/AUR).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    # Entradas
    p.add_argument("--sicar", nargs="+", required=True, metavar="ARQ",
                   help="Camada(s) do SICAR a classificar (shp/gpkg/...).")
    p.add_argument("--sicar-camada", nargs="+", default=None, metavar="NOME",
                   help="Nome da camada dentro de cada arquivo (para GeoPackage).")
    p.add_argument("--sigef", nargs="*", default=[], metavar="ARQ",
                   help="Camada(s) SIGEF da natureza escolhida.")
    p.add_argument("--snci", nargs="*", default=[], metavar="ARQ",
                   help="Camada(s) SNCI da natureza escolhida.")
    p.add_argument("--natureza", default="Privado",
                   help="Rótulo da natureza da referência (ex.: Privado/Publico).")
    p.add_argument("--tematicas", nargs="*", default=[], metavar="ARQ",
                   help="Camadas de APP/RL/AUR para o recorte (opcional).")
    p.add_argument("--col-cod", default="cod_imovel",
                   help="Nome da coluna identificadora do imóvel.")

    # Parâmetros da classificação
    p.add_argument("--iou-min", type=float, default=0.90)
    p.add_argument("--darea-max", type=float, default=0.10)
    p.add_argument("--contain-min", type=float, default=0.99)
    p.add_argument("--majority", type=float, default=0.50)
    p.add_argument("--frac-grande", type=float, default=0.50,
                   help="Fração para 'contido_menor_grande' na subdivisão.")
    p.add_argument("--piso-sobrep", type=float, default=0.01,
                   help="Piso de sobreposição entre pequenos (subdivisão).")
    p.add_argument("--limiar-sobreposicao", type=float, default=0.70,
                   help="Limiar de redundância espacial (frac_max).")

    # Controle de etapas (modularidade)
    p.add_argument("--ate", choices=ETAPAS, default="recorte",
                   help="Executa as etapas até esta (inclusive).")
    p.add_argument("--sem-subdivisao", action="store_true",
                   help="Não subdividir o contido_menor.")

    # Saída
    p.add_argument("--saida", required=True, metavar="DIR",
                   help="Diretório de saída (GeoPackages + relatório).")
    p.add_argument("--uf", default="UF",
                   help="Sigla do estado, usada nos nomes dos arquivos.")
    return p


def _ler_varias(caminhos, camadas=None):
    """Lê e concatena várias camadas (com nomes de camada opcionais)."""
    gdfs = []
    camadas = camadas or [None] * len(caminhos)
    if len(camadas) < len(caminhos):
        camadas = camadas + [None] * (len(caminhos) - len(camadas))
    for cam, nome in zip(caminhos, camadas):
        gdfs.append(ler_camada(cam, nome))
    return gdfs


def executar(args) -> dict:
    """Executa a pipeline conforme ``args`` e devolve o relatório (dict)."""
    os.makedirs(args.saida, exist_ok=True)
    rel: dict = {
        "uf": args.uf, "natureza": args.natureza,
        "quando": datetime.now(timezone.utc).isoformat(),
        "parametros": {
            "iou_min": args.iou_min, "darea_max": args.darea_max,
            "contain_min": args.contain_min, "majority": args.majority,
            "frac_grande": args.frac_grande, "piso_sobrep": args.piso_sobrep,
            "limiar_sobreposicao": args.limiar_sobreposicao,
            "subdividir": not args.sem_subdivisao, "ate": args.ate,
        },
        "entradas": {}, "etapas": {}, "conservacao": {},
    }

    cfg = ConfigPipeline(
        col_cod=args.col_cod,
        limiares=Limiares(args.iou_min, args.darea_max, args.contain_min, args.majority),
        subdividir=not args.sem_subdivisao,
        par_subdivisao=ParametrosSubdivisao(args.frac_grande, args.piso_sobrep),
        calcular_sobreposicao=(args.ate in ("sobreposicao", "recorte")),
        limiar_sobreposicao=args.limiar_sobreposicao,
    )

    # --- Leitura ---------------------------------------------------------
    print("[1/5] Lendo camadas...", file=sys.stderr)
    sicar_gdfs = _ler_varias(args.sicar, args.sicar_camada)
    sicar = concatenar(sicar_gdfs)
    rel["entradas"]["sicar"] = int(len(sicar))

    incra = _ler_varias(args.sigef) + _ler_varias(args.snci)
    referencia = montar_referencia(incra)
    rel["entradas"]["incra_parcelas"] = int(len(referencia.geoms))

    # --- Etapa 1: coerência ---------------------------------------------
    print("[2/5] Classificando coerência...", file=sys.stderr)
    res = classificar_camada_sicar(sicar, referencia, cfg, args.natureza)
    ok, _ = (res.conservacao_ok(), None)
    rel["etapas"]["coerencia"] = {
        "coerentes": int(len(res.coerentes)),
        "incoerentes": int(len(res.incoerentes)),
    }
    rel["conservacao"]["coerencia"] = bool(res.conservacao_ok())

    pref = f"{args.uf}_{args.natureza}"
    gpkg = os.path.join(args.saida, f"conformidade_{pref}.gpkg")
    escrever_camada(res.coerentes, gpkg, f"{pref}_Coerentes")
    escrever_camada(res.incoerentes, gpkg, f"{pref}_Incoerentes")

    coer = res.coerentes

    # --- Etapa 2: sobreposição ------------------------------------------
    if args.ate in ("sobreposicao", "recorte"):
        print("[3/5] Calculando sobreposição espacial...", file=sys.stderr)
        coer = aplicar_sobreposicao(res.coerentes, cfg)
        n_red = int((coer["classe_espacial"] == "redundante_sobreposto").sum())
        n_rep = int((coer["classe_espacial"] == "representante").sum())
        rel["etapas"]["sobreposicao"] = {
            "representantes": n_rep, "redundantes": n_red,
            "limiar": args.limiar_sobreposicao,
        }
        rel["conservacao"]["sobreposicao"] = (n_red + n_rep == len(res.coerentes))
        escrever_camada(coer, gpkg, f"{pref}_Coerentes")  # regrava com os campos

    # --- Etapa 3: recorte temático --------------------------------------
    if args.ate == "recorte" and args.tematicas:
        print("[4/5] Recortando APP/RL/AUR dos coerentes...", file=sys.stderr)
        tem_gdfs = _ler_varias(args.tematicas)
        cods = set(coer[args.col_cod])
        # mapa de atributos por cod para anexar às temáticas
        cols_attr = ["motivo"]
        if "classe_espacial" in coer.columns:
            cols_attr += ["classe_espacial", "frac_max", "pai_cod"]
        attr = {
            row[args.col_cod]: {c: row[c] for c in cols_attr}
            for _, row in coer.iterrows()
        }
        rotulos = [os.path.splitext(os.path.basename(t))[0] for t in args.tematicas]
        tematicas = filtrar_tematicas(
            tem_gdfs, cods, col_cod=args.col_cod,
            rotulos=rotulos, atributos_por_cod=attr,
        )
        rel["etapas"]["recorte"] = {"feicoes_tematicas": int(len(tematicas))}
        if len(tematicas) > 0:
            gpkg_tem = os.path.join(args.saida, f"tematicas_{pref}.gpkg")
            escrever_camada(tematicas, gpkg_tem, f"APP_RL_AUR_{pref}")

    # --- Relatório -------------------------------------------------------
    print("[5/5] Gravando relatório...", file=sys.stderr)
    rel_path = os.path.join(args.saida, f"relatorio_{pref}.json")
    with open(rel_path, "w", encoding="utf-8") as fh:
        json.dump(rel, fh, ensure_ascii=False, indent=2, default=str)
    return rel


def main(argv=None) -> int:
    args = construir_parser().parse_args(argv)
    rel = executar(args)
    # Resumo legível no terminal.
    print("\n=== RESUMO ===")
    print(f"UF: {rel['uf']} | natureza: {rel['natureza']}")
    print(f"SICAR de entrada: {rel['entradas']['sicar']}")
    ecoer = rel["etapas"]["coerencia"]
    print(f"Coerentes: {ecoer['coerentes']} | Incoerentes: {ecoer['incoerentes']}")
    if "sobreposicao" in rel["etapas"]:
        es = rel["etapas"]["sobreposicao"]
        print(f"Representantes: {es['representantes']} | "
              f"Redundantes(>={es['limiar']}): {es['redundantes']}")
    if "recorte" in rel["etapas"]:
        print(f"Feições temáticas: {rel['etapas']['recorte']['feicoes_tematicas']}")
    todas_ok = all(rel["conservacao"].values())
    print(f"Conservação: {'OK' if todas_ok else 'FALHOU — verificar!'}")
    return 0 if todas_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
