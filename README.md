# Conformidade SICAR × INCRA

Programa para classificar a **coerência** entre os imóveis do **SICAR** (Cadastro
Ambiental Rural) e a delimitação fundiária do **INCRA** (bases **SIGEF** e
**SNCI**), com **filtro de sobreposição espacial** e **recorte das camadas
temáticas** (APP, RL, AUR).

Roda de forma **independente do QGIS**, por linha de comando, o que permite
processar vários estados de maneira automática e reproduzível.

> Metodologia completa em [`docs/metodologia.md`](docs/metodologia.md).

---

## O que o programa faz

O processo tem **dois comandos**, na ordem natural de trabalho:

**`preparar`** (etapa 0) — parte dos dados brutos baixados do SICAR e separa os
imóveis pela fase de análise (campo `des_condic`):

- **Cancelado** → descartado (não entra na análise);
- **Analisado** → guardado num GeoPackage próprio do estado
  (`<UF>_analisados.gpkg`), junto com todos os nove planos de informação
  (APPS, RESERVA_LEGAL, etc.), para análises futuras;
- **Em Análise + Aguardando Análise** → GeoPackage de trabalho
  (`<UF>_trabalho.gpkg`), que alimenta a análise de conformidade.

**`analisar`** — roda sobre o pacote de trabalho a sequência de etapas (cada uma
pode ser ligada/desligada com `--ate`):

1. **Coerência** — classifica cada imóvel contra a referência do INCRA,
   atribuindo `motivo` (5 classes) e as métricas geométricas.
2. **Subdivisão** — (opcional) refina o `contido_menor` em `grande` / `isolado`
   / `sobreposto`.
3. **Sobreposição interna** — marca a redundância espacial entre os imóveis de
   trabalho (`classe_espacial`, `frac_max`, `pai_cod`).
4. **Filtro final contra Analisados** — remove os representantes que se
   sobrepõem a imóveis já **Analisado** (que têm prioridade e nunca são
   removidos). O resultado fica sem sobreposição entre imóveis do SICAR,
   **independente da fase**. Registra `vs_analisado`, `frac_analisado` e a
   coluna decisória `selecao_final`.
5. **Recorte** — para os imóveis `Representante (manter)`, anexa as camadas
   **APPS, RESERVA_LEGAL e USO_RESTRITO** (filtradas pelo código do imóvel).

A cada etapa, o programa confere a **conservação** (nenhum imóvel perdido ou
duplicado) e grava um relatório com os parâmetros usados.

---

## Fluxo em um olhar

```
   Download SICAR (9 planos, shapefile)
                │
                ▼
        ┌───────────────┐
        │   preparar    │  separa por des_condic
        └───────┬───────┘
        ┌───────┴───────────────────────────┐
        ▼                                     ▼
  <UF>_analisados.gpkg                <UF>_trabalho.gpkg
  (Analisado + 9 planos)              (Em Análise + Aguardando)
        │                                     │
        │  (usado no filtro final)            ▼
        │                             ┌───────────────┐
        │                             │   analisar    │
        │                             │  coerência    │
        │                             │  subdivisão   │
        │                             │  sobrep. int. │
        └────────────────────────────►  filtro final │
                                      │  recorte      │
                                      └───────┬───────┘
                                              ▼
                                  conformidade_<UF>_<nat>.gpkg
                                  (Coerentes com selecao_final +
                                   APPS/RESERVA_LEGAL/USO_RESTRITO
                                   dos "Representante (manter)")
```

---

## Instalação

### 1. Pré-requisitos

- **Python 3.10 ou superior**. Para conferir se já tem, abra o terminal e digite:
  ```bash
  python --version
  ```
- As bibliotecas geoespaciais (GeoPandas e companhia). A forma mais simples de
  ter tudo funcionando é usar o **conda/miniconda**, que já traz as dependências
  espaciais compiladas.

### 2. Baixar o programa

```bash
git clone https://github.com/Geconsult-code/Conformidade_sicar-incra.git
cd Conformidade_sicar-incra
```

### 3. Instalar as dependências

**Opção A — com conda (recomendada):**
```bash
conda create -n conformidade python=3.11 geopandas -c conda-forge
conda activate conformidade
pip install -e .
```

**Opção B — com pip:**
```bash
pip install -r requirements.txt
pip install -e .
```

O `pip install -e .` instala o comando `conformidade` no seu ambiente. Para
testar:
```bash
conformidade --help
```

---

## Como usar (tutorial)

O processo tem dois passos: **`preparar`** (uma vez por estado, a partir do
download) e **`analisar`** (a conformidade em si).

### Passo 1 — Baixe os dados do estado

No portal do SICAR (https://consultapublica.car.gov.br/publico/estados/downloads),
baixe os planos do estado em shapefile. Você terá pastas com os nomes:
`AREA_IMOVEL`, `APPS`, `RESERVA_LEGAL`, `USO_RESTRITO`, `AREA_CONSOLIDADA`,
`AREA_POUSIO`, `HIDROGRAFIA`, `SERVIDAO_ADMINISTRATIVA`, `VEGETACAO_NATIVA`.

Separadamente, tenha a referência do INCRA (**SIGEF** e **SNCI**) da natureza
que vai analisar (privada ou pública).

### Passo 2 — `preparar`: separe os imóveis por fase

```bash
conformidade preparar \
  --area-imovel        AREA_IMOVEL/AREA_IMOVEL.shp \
  --apps               APPS/APPS.shp \
  --reserva-legal      RESERVA_LEGAL/RESERVA_LEGAL.shp \
  --uso-restrito       USO_RESTRITO/USO_RESTRITO.shp \
  --area-consolidada   AREA_CONSOLIDADA/AREA_CONSOLIDADA.shp \
  --area-pousio        AREA_POUSIO/AREA_POUSIO.shp \
  --hidrografia        HIDROGRAFIA/HIDROGRAFIA.shp \
  --servidao-administrativa SERVIDAO_ADMINISTRATIVA/SERVIDAO_ADMINISTRATIVA.shp \
  --vegetacao-nativa   VEGETACAO_NATIVA/VEGETACAO_NATIVA.shp \
  --uf PA --saida preparo_PA/
```

Isso gera, na pasta `preparo_PA/`:

| Arquivo | Conteúdo |
|---------|----------|
| `PA_trabalho.gpkg` | imóveis **Em Análise + Aguardando** (camada `AREA_IMOVEL`) |
| `PA_analisados.gpkg` | imóveis **Analisado** + todos os nove planos filtrados |
| `preparacao_PA.json` | contagem por fase |

> Só o `AREA_IMOVEL` é obrigatório. Os demais planos são usados para compor o
> pacote de analisados; informe ao menos APPS, RESERVA_LEGAL e USO_RESTRITO, que
> são necessários no recorte final da análise.

### Passo 3 — `analisar`: rode a conformidade

```bash
conformidade analisar \
  --sicar       preparo_PA/PA_trabalho.gpkg --sicar-camada AREA_IMOVEL \
  --sigef       SIGEF_Privado.shp \
  --snci        SNCI_Privado.shp \
  --natureza    Privado \
  --analisados  preparo_PA/PA_analisados.gpkg --analisados-camada AREA_IMOVEL \
  --apps          APPS/APPS.shp \
  --reserva-legal RESERVA_LEGAL/RESERVA_LEGAL.shp \
  --uso-restrito  USO_RESTRITO/USO_RESTRITO.shp \
  --limiar-sobreposicao 0.10 \
  --limiar-vs-analisado 0.30 \
  --uf PA --saida resultado_PA/
```

Controle de etapas com `--ate`: `coerencia`, `sobreposicao`, `final` ou
`recorte` (padrão). Para pular a subdivisão do `contido_menor`, acrescente
`--sem-subdivisao`. O `--analisados` é opcional — sem ele, o filtro final é
ignorado (todos os representantes seguem).

### Passo 4 — Veja os resultados

Na pasta `resultado_PA/`:

| Arquivo | Conteúdo |
|---------|----------|
| `conformidade_PA_Privado.gpkg` | `..._Coerentes`, `..._Incoerentes` e as camadas `APPS`/`RESERVA_LEGAL`/`USO_RESTRITO` dos imóveis a manter |
| `relatorio_PA_Privado.json` | parâmetros, contagens por etapa e conservação |

Campos principais na camada de coerentes:

- **`motivo`** — a classe de coerência (5 valores);
- **`classe_espacial`** — `representante`/`redundante_sobreposto` (sobreposição interna);
- **`frac_max`** — cobertura máxima por um imóvel maior (0 a 1);
- **`vs_analisado`** — `livre` ou `sobrepoe_analisado`;
- **`frac_analisado`** — cobertura máxima por um imóvel Analisado;
- **`selecao_final`** — **`Representante (manter)`**, `redundante_interno` ou
  `sobrepoe_analisado`. Este é o campo decisório: os `Representante (manter)`
  são o conjunto final, sem sobreposição entre si nem com os Analisados.

### Recalibrar os limiares sem reprocessar

Como `frac_max` e `frac_analisado` ficam gravados em cada imóvel, você pode
testar outros cortes filtrando direto no QGIS/ArcGIS
(`frac_max >= 0.30`, `frac_analisado >= 0.20` etc.), sem rodar de novo. Só é
preciso reprocessar ao mudar os parâmetros da *classificação* (IoU, containment).

---

## Principais opções da linha de comando

**`preparar`**

| Opção | Obrigatório | O que faz |
|-------|-------------|-----------|
| `--area-imovel` | sim | plano AREA_IMOVEL (tem o `des_condic`) |
| `--apps`, `--reserva-legal`, `--uso-restrito`, ... | não | demais planos, para o pacote de analisados |
| `--uf`, `--saida` | sim | sigla do estado e pasta de saída |

**`analisar`**

| Opção | Padrão | O que faz |
|-------|--------|-----------|
| `--sicar` | — | camada(s) de trabalho (obrigatório) |
| `--sigef` / `--snci` | — | referência do INCRA |
| `--natureza` | `Privado` | rótulo da natureza (Privado/Publico) |
| `--analisados` | — | camada dos imóveis Analisado (filtro final) |
| `--apps` / `--reserva-legal` / `--uso-restrito` | — | temáticas do recorte final |
| `--ate` | `recorte` | etapa final (`coerencia`/`sobreposicao`/`final`/`recorte`) |
| `--sem-subdivisao` | desligado | não subdivide o `contido_menor` |
| `--limiar-sobreposicao` | `0.10` | corte da sobreposição interna |
| `--limiar-vs-analisado` | `0.30` | corte do filtro contra Analisados (calibrado no Pará) |
| `--iou-min` | `0.90` | IoU mínimo para `forma_similar` |
| `--contain-min` | `0.99` | contenção mínima (Ramo A) |
| `--darea-max` | `0.10` | diferença de área tolerada |
| `--uf` / `--saida` | — | sigla do estado e pasta de saída (saída obrigatória) |

Lista completa: `conformidade preparar --help` e `conformidade analisar --help`.

---

## Uso como biblioteca (para quem programa)

Todo o núcleo é importável:

```python
from conformidade.io_dados import ler_camada
from conformidade.pipeline import (
    ConfigPipeline, montar_referencia, classificar_camada_sicar, aplicar_sobreposicao,
)

sicar = ler_camada("SICAR_Aguardando.shp")
ref = montar_referencia([ler_camada("SIGEF_Privado.shp"), ler_camada("SNCI_Privado.shp")])
cfg = ConfigPipeline(limiar_sobreposicao=0.70)

res  = classificar_camada_sicar(sicar, ref, cfg, natureza="Privado")
coer = aplicar_sobreposicao(res.coerentes, cfg)
print(len(res.coerentes), "coerentes;", (coer.classe_espacial == "representante").sum(), "representantes")
```

---

## Validação

A metodologia foi construída e validada a partir de uma rotina desenvolvida
manualmente no QGIS para o estado do **Pará**. A classificação de coerência do
programa reproduz o resultado do QGIS com **99,4% de concordância** imóvel a
imóvel (as divergências restantes são todas de fronteira — imóveis exatamente
sobre os limiares, onde diferenças mínimas de arredondamento entre motores
geométricos decidem o lado). O fluxo completo (preparação por fase,
classificação, sobreposição, filtro contra Analisados e recorte) foi então
executado de ponta a ponta no Pará, servindo de modelo para os demais estados.

Os testes automatizados em [`exemplos/teste_nucleo.py`](exemplos/teste_nucleo.py)
verificam o núcleo (os cinco motivos, a sobreposição, a subdivisão, as fases e o
filtro contra Analisados) e podem ser executados a qualquer momento:

```bash
python exemplos/teste_nucleo.py
```

---

## Estrutura do repositório

```
conformidade/            # biblioteca (núcleo reutilizável)
  geometria.py           #   área geodésica GRS80, validação
  fases.py               #   identificação de fase por des_condic
  preparacao.py          #   etapa 0: separa por fase, monta os GeoPackages
  classificacao.py       #   coerência (ramos A/B/C, 5 motivos)
  subdivisao.py          #   subdivisão do contido_menor
  sobreposicao.py        #   sobreposição interna + filtro contra Analisados
  recorte.py             #   recorte APPS/RESERVA_LEGAL/USO_RESTRITO
  io_dados.py            #   leitura/escrita, conservação
  pipeline.py            #   orquestração modular
  cli.py                 #   linha de comando (preparar / analisar)
separar_incra_por_uf.py  # utilitário: separa SIGEF/SNCI nacionais por estado
docs/metodologia.md      # documentação científica
exemplos/teste_nucleo.py # testes automatizados do núcleo
```

---

## Autoria

Desenvolvido por **Maurício Braga Meira** — **Geoconsult Ltda.**
(Consultoria especializada em geoinformação).

## Como citar

Se este software for útil no seu trabalho, por favor cite-o. O GitHub gera a
citação automaticamente a partir do arquivo [`CITATION.cff`](CITATION.cff)
(botão **"Cite this repository"**, no alto da página do repositório). Formato
sugerido:

> Braga Meira, M. (2026). *Conformidade SICAR × INCRA* (v0.1.0) [software].
> Geoconsult Ltda. https://github.com/Geconsult-code/Conformidade_sicar-incra

## Licença

MIT — veja [`LICENSE`](LICENSE).
