"""
cli.py — interface de linha de comando da análise de conformidade SICAR × INCRA.

Dois subcomandos:

  conformidade preparar   — etapa 0: a partir dos dados brutos do SICAR (pastas
                            AREA_IMOVEL, APPS, RESERVA_LEGAL, ...), separa os
                            imóveis por fase (des_condic) e gera dois
                            GeoPackages por estado:
                              <UF>_analisados.gpkg  (Analisado + todos os planos)
                              <UF>_trabalho.gpkg    (Em Análise + Aguardando)

  conformidade analisar   — classifica a coerência SICAR × INCRA sobre o pacote
                            de trabalho, aplica a sobreposição interna, o filtro
                            final contra os imóveis Analisado e, para os
                            "Representantes (manter)", anexa as camadas APPS,
                            RESERVA_LEGAL e USO_RESTRITO.

Este módulo apenas orquestra I/O + chamadas à biblioteca ``conformidade``.
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
    aplicar_sobreposicao, aplicar_filtro_analisados,
)
from .recorte import filtrar_tematicas
from .preparacao import preparar_estado, PLANOS_PADRAO, PLANOS_TEMATICOS_FINAIS


# ======================================================================
# Subcomando: preparar
# ======================================================================

def _add_preparar(sub):
    p = sub.add_parser(
        "preparar",
        help="Etapa 0: separa imóveis por fase e monta os GeoPackages do estado.",
        description="A partir dos planos brutos do SICAR, separa Analisado / "
                    "Em Análise / Aguardando (descarta Cancelado) e grava "
                    "<UF>_analisados.gpkg e <UF>_trabalho.gpkg.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--area-imovel", required=True, metavar="ARQ",
                   help="Caminho do plano AREA_IMOVEL (obrigatório).")
    for nome in PLANOS_PADRAO:
        if nome == "AREA_IMOVEL":
            continue
        p.add_argument(f"--{nome.lower().replace('_', '-')}", metavar="ARQ",
                       help=f"Caminho do plano {nome}.")
    p.add_argument("--col-cod", default="cod_imovel")
    p.add_argument("--col-fase", default="des_condic")
    p.add_argument("--uf", required=True)
    p.add_argument("--saida", required=True, metavar="DIR")
    p.set_defaults(func=_run_preparar)


def _run_preparar(args) -> int:
    planos = {"AREA_IMOVEL": args.area_imovel}
    for nome in PLANOS_PADRAO:
        if nome == "AREA_IMOVEL":
            continue
        val = getattr(args, nome.lower(), None)
        if val:
            planos[nome] = val

    print(f"[preparar {args.uf}] lendo AREA_IMOVEL e separando por fase...",
          file=sys.stderr)
    res = preparar_estado(planos, args.uf, args.saida,
                          col_cod=args.col_cod, col_fase=args.col_fase)

    resumo = res.resumo()
    with open(os.path.join(args.saida, f"preparacao_{args.uf}.json"), "w",
              encoding="utf-8") as fh:
        json.dump(resumo, fh, ensure_ascii=False, indent=2, default=str)

    print("\n=== PREPARAÇÃO ===")
    print(f"UF: {resumo['uf']}")
    print(f"Analisado:  {resumo['analisado']}  -> {os.path.basename(res.gpkg_analisados)}")
    print(f"Em Análise: {resumo['em_analise']}")
    print(f"Aguardando: {resumo['aguardando']}")
    print(f"  (trabalho = {resumo['em_analise'] + resumo['aguardando']})"
          f"  -> {os.path.basename(res.gpkg_trabalho)}")
    print(f"Cancelado (descartado): {resumo['cancelado_descartado']}")
    return 0


# ======================================================================
# Subcomando: analisar
# ======================================================================

def _add_analisar(sub):
    p = sub.add_parser(
        "analisar",
        help="Classifica coerência + sobreposição + filtro vs Analisados + recorte.",
        description="Roda a conformidade sobre o pacote de trabalho e, para os "
                    "Representantes, anexa APPS/RESERVA_LEGAL/USO_RESTRITO.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--sicar", nargs="+", required=True, metavar="ARQ",
                   help="Camada(s) do SICAR de trabalho (Em Análise + Aguardando).")
    p.add_argument("--sicar-camada", nargs="+", default=None, metavar="NOME")
    p.add_argument("--sigef", nargs="*", default=[], metavar="ARQ")
    p.add_argument("--snci", nargs="*", default=[], metavar="ARQ")
    p.add_argument("--natureza", default="Privado")
    p.add_argument("--analisados", default=None, metavar="ARQ",
                   help="Camada dos imóveis Analisado (filtro final). Opcional.")
    p.add_argument("--analisados-camada", default=None, metavar="NOME")
    p.add_argument("--apps", nargs="*", default=None, metavar="ARQ",
                   help="Camada(s) APPS; aceita vários arquivos (planos fatiados).")
    p.add_argument("--reserva-legal", nargs="*", default=None, metavar="ARQ",
                   help="Camada(s) RESERVA_LEGAL; aceita vários arquivos.")
    p.add_argument("--uso-restrito", nargs="*", default=None, metavar="ARQ",
                   help="Camada(s) USO_RESTRITO; aceita vários arquivos.")
    p.add_argument("--col-cod", default="cod_imovel")

    p.add_argument("--iou-min", type=float, default=0.90)
    p.add_argument("--darea-max", type=float, default=0.10)
    p.add_argument("--contain-min", type=float, default=0.99)
    p.add_argument("--majority", type=float, default=0.50)
    p.add_argument("--frac-grande", type=float, default=0.50)
    p.add_argument("--piso-sobrep", type=float, default=0.01)
    p.add_argument("--limiar-sobreposicao", type=float, default=0.10,
                   help="Limiar da sobreposição interna (Em/Aguardando).")
    p.add_argument("--limiar-vs-analisado", type=float, default=0.10,
                   help="Limiar do filtro final contra os imóveis Analisado.")

    p.add_argument("--ate", choices=["coerencia", "sobreposicao", "final", "recorte"],
                   default="recorte",
                   help="Executa as etapas até esta (inclusive).")
    p.add_argument("--sem-subdivisao", action="store_true")

    p.add_argument("--saida", required=True, metavar="DIR")
    p.add_argument("--uf", default="UF")
    p.set_defaults(func=_run_analisar)


def _ler_varias(caminhos, camadas=None):
    gdfs = []
    camadas = camadas or [None] * len(caminhos)
    if len(camadas) < len(caminhos):
        camadas = camadas + [None] * (len(caminhos) - len(camadas))
    for cam, nome in zip(caminhos, camadas):
        gdfs.append(ler_camada(cam, nome))
    return gdfs


def _run_analisar(args) -> int:
    os.makedirs(args.saida, exist_ok=True)
    rel: dict = {
        "uf": args.uf, "natureza": args.natureza,
        "quando": datetime.now(timezone.utc).isoformat(),
        "parametros": {
            "iou_min": args.iou_min, "darea_max": args.darea_max,
            "contain_min": args.contain_min, "majority": args.majority,
            "frac_grande": args.frac_grande, "piso_sobrep": args.piso_sobrep,
            "limiar_sobreposicao": args.limiar_sobreposicao,
            "limiar_vs_analisado": args.limiar_vs_analisado,
            "subdividir": not args.sem_subdivisao, "ate": args.ate,
        },
        "entradas": {}, "etapas": {}, "conservacao": {},
    }

    cfg = ConfigPipeline(
        col_cod=args.col_cod,
        limiares=Limiares(args.iou_min, args.darea_max, args.contain_min, args.majority),
        subdividir=not args.sem_subdivisao,
        par_subdivisao=ParametrosSubdivisao(args.frac_grande, args.piso_sobrep),
        limiar_sobreposicao=args.limiar_sobreposicao,
        limiar_vs_analisado=args.limiar_vs_analisado,
    )

    print("[1/6] Lendo camadas...", file=sys.stderr)
    sicar = concatenar(_ler_varias(args.sicar, args.sicar_camada))
    rel["entradas"]["sicar_trabalho"] = int(len(sicar))
    referencia = montar_referencia(_ler_varias(args.sigef) + _ler_varias(args.snci))
    rel["entradas"]["incra_parcelas"] = int(len(referencia.geoms))

    print("[2/6] Classificando coerência...", file=sys.stderr)
    res = classificar_camada_sicar(sicar, referencia, cfg, args.natureza)
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

    if args.ate in ("sobreposicao", "final", "recorte"):
        print("[3/6] Sobreposição interna (Em/Aguardando)...", file=sys.stderr)
        coer = aplicar_sobreposicao(res.coerentes, cfg)
        n_red = int((coer["classe_espacial"] == "redundante_sobreposto").sum())
        n_rep = int((coer["classe_espacial"] == "representante").sum())
        rel["etapas"]["sobreposicao_interna"] = {
            "representantes": n_rep, "redundantes": n_red,
            "limiar": args.limiar_sobreposicao,
        }
        escrever_camada(coer, gpkg, f"{pref}_Coerentes")

    if args.ate in ("final", "recorte"):
        print("[4/6] Filtro final contra imóveis Analisado...", file=sys.stderr)
        analisados = None
        if args.analisados:
            analisados = ler_camada(args.analisados, args.analisados_camada)
            rel["entradas"]["analisados"] = int(len(analisados))
        coer = aplicar_filtro_analisados(coer, analisados, cfg)
        n_manter = int((coer["selecao_final"] == "Representante (manter)").sum())
        rel["etapas"]["filtro_final"] = {
            "manter": n_manter,
            "redundante_interno": int((coer["selecao_final"] == "redundante_interno").sum()),
            "sobrepoe_analisado": int((coer["selecao_final"] == "sobrepoe_analisado").sum()),
            "limiar_vs_analisado": args.limiar_vs_analisado,
        }
        rel["conservacao"]["filtro_final"] = (len(coer) == len(res.coerentes))
        escrever_camada(coer, gpkg, f"{pref}_Coerentes")

    if args.ate == "recorte":
        print("[5/6] Recortando APPS/RESERVA_LEGAL/USO_RESTRITO dos "
              "Representantes...", file=sys.stderr)
        manter = coer[coer["selecao_final"] == "Representante (manter)"]
        cods = set(manter[args.col_cod])
        cols_attr = ["motivo", "classe_espacial", "frac_max", "pai_cod",
                     "selecao_final"]
        cols_attr = [c for c in cols_attr if c in manter.columns]
        attr = {
            row[args.col_cod]: {c: row[c] for c in cols_attr}
            for _, row in manter.iterrows()
        }
        temas = {"APPS": args.apps, "RESERVA_LEGAL": args.reserva_legal,
                 "USO_RESTRITO": args.uso_restrito}
        n_total = 0
        for nome in PLANOS_TEMATICOS_FINAIS:
            caminhos = temas.get(nome)
            if not caminhos:
                continue
            # aceita vários arquivos (planos fatiados: APPS_2..APPS_6, etc.)
            gdfs = [ler_camada(c) for c in caminhos]
            # salvaguarda: descarta feições temáticas em fase Cancelado
            # (o mesmo cod_imovel pode ter linhas canceladas por duplicidade)
            from .fases import classificar_fase, CANCELADO
            gdfs_limpos = []
            for g in gdfs:
                if "des_condic" in g.columns:
                    fase_feicao = g["des_condic"].map(classificar_fase)
                    g = g[fase_feicao != CANCELADO]
                gdfs_limpos.append(g)
            sel = filtrar_tematicas(gdfs_limpos, cods, col_cod=args.col_cod,
                                    rotulos=[nome] * len(gdfs_limpos),
                                    atributos_por_cod=attr)
            if len(sel) > 0:
                escrever_camada(sel, gpkg, nome)
                n_total += len(sel)
        rel["etapas"]["recorte"] = {
            "imoveis_manter": int(len(cods)), "feicoes_tematicas": int(n_total),
        }

    print("[6/6] Gravando relatório...", file=sys.stderr)
    rel_path = os.path.join(args.saida, f"relatorio_{pref}.json")
    with open(rel_path, "w", encoding="utf-8") as fh:
        json.dump(rel, fh, ensure_ascii=False, indent=2, default=str)

    print("\n=== RESUMO ===")
    print(f"UF: {rel['uf']} | natureza: {rel['natureza']}")
    print(f"SICAR (trabalho): {rel['entradas']['sicar_trabalho']}")
    ec = rel["etapas"]["coerencia"]
    print(f"Coerentes: {ec['coerentes']} | Incoerentes: {ec['incoerentes']}")
    if "sobreposicao_interna" in rel["etapas"]:
        es = rel["etapas"]["sobreposicao_interna"]
        print(f"Sobreposicao interna(>={es['limiar']}): "
              f"{es['representantes']} representantes / {es['redundantes']} redundantes")
    if "filtro_final" in rel["etapas"]:
        ef = rel["etapas"]["filtro_final"]
        print(f"Filtro vs Analisado(>={ef['limiar_vs_analisado']}): "
              f"MANTER {ef['manter']} | "
              f"redundante_interno {ef['redundante_interno']} | "
              f"sobrepoe_analisado {ef['sobrepoe_analisado']}")
    if "recorte" in rel["etapas"]:
        er = rel["etapas"]["recorte"]
        print(f"Recorte tematico (APPS/RL/USO_RESTRITO): "
              f"{er['feicoes_tematicas']} feicoes de {er['imoveis_manter']} imoveis")
    todas_ok = all(rel["conservacao"].values())
    print(f"Conservacao: {'OK' if todas_ok else 'FALHOU — verificar!'}")
    return 0 if todas_ok else 2


# ======================================================================
# Parser principal
# ======================================================================

def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="conformidade",
        description="Conformidade SICAR × INCRA: preparacao por fase, "
                    "classificacao de coerencia, sobreposicao espacial e "
                    "recorte tematico.",
    )
    sub = p.add_subparsers(dest="comando", required=True)
    _add_preparar(sub)
    _add_analisar(sub)
    return p


def main(argv=None) -> int:
    args = construir_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
