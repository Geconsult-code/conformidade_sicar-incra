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

A partir das bases de um estado, o programa executa uma sequência de etapas
(cada uma pode ser ligada/desligada):

1. **Coerência** — classifica cada imóvel do SICAR contra a referência do INCRA,
   atribuindo a categoria `motivo` (5 classes) e as métricas geométricas.
2. **Subdivisão** — (opcional) refina o `contido_menor` em `grande` / `isolado`
   / `sobreposto`.
3. **Sobreposição** — (opcional) marca a redundância espacial entre imóveis
   (`classe_espacial`, `frac_max`, `pai_cod`), para evitar dupla contagem de
   área.
4. **Recorte** — (opcional) filtra as feições de APP/RL/AUR dos imóveis
   coerentes.

A cada etapa, o programa confere a **conservação** (nenhum imóvel perdido ou
duplicado) e grava um relatório com os parâmetros usados.

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

### Passo 1 — Organize os dados do estado

Baixe e deixe numa pasta os arquivos do estado (shapefile ou GeoPackage):

- SICAR "Em Análise" e "Aguardando Análise";
- referência do INCRA da natureza que você quer analisar (**privada** ou
  **pública**): SIGEF e SNCI;
- (opcional) as camadas de APP, RL e AUR.

> **Importante:** rode uma natureza por vez. Para os **privados**, use
> `SIGEF_Privado` + `SNCI_Privado`; para os **públicos**, as versões públicas.
> Ver o porquê em [`docs/metodologia.md`](docs/metodologia.md).

### Passo 2 — Rode o comando

Exemplo completo (natureza privada, pipeline inteira) — **troque os caminhos
pelos seus arquivos**:

```bash
conformidade \
  --sicar  SICAR_Em_Analise.shp  SICAR_Aguardando_Analise.shp \
  --sigef  SIGEF_Privado.shp \
  --snci   SNCI_Privado.shp \
  --natureza Privado \
  --tematicas  APP.shp  RL.shp  AUR.shp \
  --limiar-sobreposicao 0.70 \
  --uf PA \
  --saida  resultado_PA/
```

Para rodar **só até a coerência** (sem sobreposição nem recorte):
```bash
conformidade --sicar SICAR.shp --sigef SIGEF_Privado.shp --snci SNCI_Privado.shp \
             --natureza Privado --ate coerencia --uf PA --saida resultado_PA/
```

Para **pular a subdivisão** do `contido_menor`, acrescente `--sem-subdivisao`.

### Passo 3 — Veja os resultados

Na pasta de saída você terá:

| Arquivo | Conteúdo |
|---------|----------|
| `conformidade_PA_Privado.gpkg` | camadas `..._Coerentes` e `..._Incoerentes` |
| `tematicas_PA_Privado.gpkg` | APP/RL/AUR recortados dos coerentes |
| `relatorio_PA_Privado.json` | parâmetros, contagens e verificação de conservação |

Abra os GeoPackages no QGIS ou ArcGIS. Os campos principais:

- **`motivo`** — a classe de coerência (5 valores);
- **`classe_espacial`** — `representante` ou `redundante_sobreposto`;
- **`frac_max`** — cobertura máxima por um imóvel maior (0 a 1);
- **`tipo_incra`** — natureza da referência (Privado/Publico).

### Recalibrar o limiar de sobreposição

Como o `frac_max` fica gravado em cada imóvel, você pode testar outro corte
**sem reprocessar**: no QGIS/ArcGIS, filtre por `frac_max >= 0.30` (ou qualquer
valor). Só é preciso rodar de novo se mudar os parâmetros da *classificação*
(IoU, containment etc.).

---

## Principais opções da linha de comando

| Opção | Padrão | O que faz |
|-------|--------|-----------|
| `--sicar` | — | camada(s) do SICAR a classificar (obrigatório) |
| `--sigef` / `--snci` | — | referência do INCRA |
| `--natureza` | `Privado` | rótulo da natureza (Privado/Publico) |
| `--tematicas` | — | camadas APP/RL/AUR para o recorte |
| `--ate` | `recorte` | executa até esta etapa (`coerencia`/`sobreposicao`/`recorte`) |
| `--sem-subdivisao` | desligado | não subdivide o `contido_menor` |
| `--limiar-sobreposicao` | `0.70` | corte de redundância espacial |
| `--iou-min` | `0.90` | IoU mínimo para `forma_similar` |
| `--contain-min` | `0.99` | contenção mínima (Ramo A) |
| `--darea-max` | `0.10` | diferença de área tolerada |
| `--uf` | `UF` | sigla do estado (nomes dos arquivos) |
| `--saida` | — | pasta de saída (obrigatório) |

Lista completa: `conformidade --help`.

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

O programa foi construído a partir de uma rotina validada manualmente no QGIS
para o estado do **Pará**. O script [`exemplos/validar_para.py`](exemplos/validar_para.py)
compara, imóvel a imóvel, o resultado do programa com o resultado de referência
do Pará — é a garantia de que a "tradução" da rotina para código preserva os
números. Rode-o antes de processar novos estados.

---

## Estrutura do repositório

```
conformidade/            # biblioteca (núcleo reutilizável)
  geometria.py           #   área geodésica GRS80, validação
  classificacao.py       #   coerência (ramos A/B/C, 5 motivos)
  subdivisao.py          #   subdivisão do contido_menor
  sobreposicao.py        #   filtro de sobreposição espacial
  recorte.py             #   recorte APP/RL/AUR
  io_dados.py            #   leitura/escrita, conservação
  pipeline.py            #   orquestração modular
  cli.py                 #   linha de comando
docs/metodologia.md      # documentação científica
exemplos/                # validação e exemplos
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
