# Metodologia — Conformidade SICAR × INCRA

Este documento descreve a metodologia de classificação da coerência entre os
imóveis do **SICAR** (Sistema de Cadastro Ambiental Rural) e a delimitação
fundiária do **INCRA** (bases **SIGEF** e **SNCI**), incluindo o filtro de
sobreposição espacial e o recorte das camadas temáticas (APP, RL, AUR).

## 1. Objetivo

Identificar os imóveis do SICAR — nas fases **"Em Análise"** e **"Aguardando
Análise"** — que, embora ainda não analisados pelo órgão competente, mostram-se
**coerentes**, ao menos em termos de delimitação, com o cadastro do INCRA. A
premissa é que o cadastro do INCRA (imóveis escriturados, via SIGEF/SNCI) é a
referência geométrica mais precisa disponível, por não ser meramente
declaratório como o SICAR.

Uma vez identificados os imóveis coerentes, o objetivo seguinte é analisar as
áreas de **APP** (Área de Preservação Permanente), **RL** (Reserva Legal) e
**AUR** (Área de Uso Restrito) desses imóveis — o que exige um conjunto de
imóveis **sem sobreposição espacial entre si**, para evitar dupla contagem de
área.

## 2. Bases de entrada

| Base | Papel | Observação |
|------|-------|------------|
| SICAR "Em Análise" | imóveis a classificar | declaratório |
| SICAR "Aguardando Análise" | imóveis a classificar | declaratório |
| SIGEF | referência (INCRA) | georreferenciado, escriturado |
| SNCI | referência (INCRA) | georreferenciado, escriturado |
| APP / RL / AUR | camadas temáticas do CAR | mesma chave `cod_imovel` |

Todas as bases são harmonizadas para **EPSG:4674 (SIRGAS 2000)**, datum oficial
brasileiro. O identificador único de imóvel é o `cod_imovel`.

### Separação por natureza (pública × privada)

A referência do INCRA é separada em **pública** (assentamentos, glebas de
reforma agrária) e **privada** (fazendas escrituradas). Essa separação é uma
decisão metodológica central: os imóveis públicos são glebas grandes que contêm
muitos lotes pequenos do SICAR (sobreposição é esperada e normal), enquanto os
privados tendem a corresponder ao imóvel do CAR aproximadamente 1:1. Misturar as
duas naturezas força a comparação de forma e gera uma massa artificial de
`contido_menor`. Por isso, a classificação é feita **independentemente** contra
cada natureza, e cada imóvel recebe o rótulo `tipo_incra`.

## 3. Classificação de coerência (categoria `motivo`)

Para cada imóvel do SICAR, mede-se a relação geométrica com a **união das
parcelas do INCRA que o intersectam**. Todas as áreas são **geodésicas**
(elipsoide GRS80), portanto independentes de projeção.

### Métricas

- **containment** = área(SICAR ∩ INCRA) / área(SICAR)
- **IoU** (Intersection over Union) = área(∩) / área(∪)
- **Δárea** = |área(SICAR) − área(INCRA)| / área(INCRA)
- **hausdorff_rel** = distância de Hausdorff normalizada — **apenas
  diagnóstica**, nunca usada no critério (é redundante com o IoU e sensível à
  escala).

### Limiares (padrão, validados no Pará)

| Parâmetro | Valor | Papel |
|-----------|-------|-------|
| `CONTAIN_MIN` | 0,99 | contenção mínima para o Ramo A |
| `DAREA_MAX` | 0,10 | diferença de área tolerada |
| `IOU_MIN` | 0,90 | IoU mínimo para "forma similar" |
| `MAJORITY` | 0,50 | maioria da parcela dentro do SICAR (caso 1:N) |

### Árvore de decisão

```
                    ┌─ containment ≥ 0,99 ? ──── SIM ──► RAMO A
  SICAR × INCRA ────┤                                    │
                    └─ NÃO                                ├─ Δárea ≤ 0,10 ► Coerente / contido_equivalente
                       │                                  └─ senão        ► Coerente / contido_menor
                       │
                       ├─ há sobreposição ? ── SIM ──► RAMO B
                       │                              │  reconstrói R' com parcelas
                       │                              │  cuja maioria (≥ 0,50) está no SICAR
                       │                              ├─ IoU ≥ 0,90 e Δárea ≤ 0,10 ► Coerente / forma_similar
                       │                              └─ senão                     ► Incoerente / forma_divergente
                       │
                       └─ sem sobreposição ─────────► RAMO C ► Incoerente / sem_sobreposicao
```

### Os cinco motivos

| motivo | classe | significado |
|--------|--------|-------------|
| `contido_equivalente` | Coerente | contido e de tamanho equivalente à referência |
| `contido_menor` | Coerente | contido, porém bem menor (lote em gleba maior) |
| `forma_similar` | Coerente | não contido, mas forma e área batem (IoU alto) |
| `forma_divergente` | Incoerente | há sobreposição, mas forma/área divergem |
| `sem_sobreposicao` | Incoerente | nenhuma sobreposição com a referência |

O Ramo B reconstrói a referência com as parcelas **majoritariamente** dentro do
SICAR justamente para tratar o caso **1:N** — um imóvel do SICAR que cobre
várias parcelas do INCRA.

## 4. Subdivisão do `contido_menor` (opcional)

Os imóveis `contido_menor` podem ser refinados em três subclasses, usando o
**INCRA-pai** (a parcela individual do INCRA de maior interseção com o imóvel) e
a fração `frac = área(SICAR) / área(INCRA-pai)`:

| subclasse | critério |
|-----------|----------|
| `contido_menor_grande` | `frac ≥ 0,50` (quase do tamanho da parcela) |
| `contido_menor_isolado` | `frac < 0,50` e **sem** sobreposição a outros pequenos na mesma parcela-pai |
| `contido_menor_sobreposto` | `frac < 0,50` e **com** sobreposição a outros pequenos na mesma parcela-pai |

O teste de sobreposição entre pequenos usa um piso de **1%** da área do menor,
para ignorar encostas mínimas de borda (imprecisão típica do SICAR).

## 5. Filtro de sobreposição espacial (categoria `classe_espacial`)

Eixo **ortogonal** ao `motivo`. Serve para evitar dupla contagem de área na
análise posterior de APP/RL/AUR: dois imóveis coerentes podem ocupar a mesma
porção do território, e nesse caso só um deve ser mantido.

### Métrica

Para o imóvel **menor** `X`, contra cada imóvel **maior** `Y`:

```
frac(X, Y) = área(X ∩ Y) / área(X)
```

- `frac_max(X)` = maior cobertura de `X` por um único imóvel maior.
- O **"pai"** é sempre o imóvel de **maior tamanho** (nunca marcado como
  redundante), presumivelmente o mais fiel à referência do INCRA.

### Classe

| `classe_espacial` | critério |
|-------------------|----------|
| `redundante_sobreposto` | `frac_max ≥ limiar` |
| `representante` | caso contrário |

O campo numérico **`frac_max`** é gravado em cada imóvel. Isso permite
**recalibrar o limiar depois apenas filtrando**, sem reprocessar geometria. O
campo `pai_cod` guarda o imóvel maior que mais cobre `X`.

> **Nota sobre o limiar.** Na validação do Pará (privados), a sensibilidade do
> número de redundantes ao limiar foi quase plana entre 10% e 70% — sinal de que
> as sobreposições são **fortes** (totais ou quase totais), não parciais. Ou
> seja, o resultado é pouco sensível ao valor exato do limiar. As pequenas
> sobreposições de borda já haviam sido tratadas com o piso de 1% na subdivisão.

## 6. Recorte temático (APP / RL / AUR)

As feições de APP, RL e AUR do CAR trazem o mesmo `cod_imovel`. O recorte é uma
**seleção por atributo** (junção pela chave), mantendo apenas as feições dos
imóveis coerentes desejados. Opcionalmente, os atributos de classificação
(`motivo`, `classe_espacial`, `frac_max`, `pai_cod`) são anexados às feições
temáticas, permitindo filtrá-las também por esses eixos. A geometria das feições
temáticas é preservada integralmente.

## 7. Conservação

Em cada etapa, o programa verifica a **conservação**: a soma das saídas deve ser
exatamente igual ao total de entrada, sem imóvel perdido ou duplicado. Isso é um
teste de sanidade permanente da execução.

## 8. Notas operacionais

- **Área geodésica**: usa-se `pyproj.Geod(ellps="GRS80")`, equivalente ao
  `QgsDistanceArea` com GRS80. Reprojeções para uma projeção métrica introduzem
  distorção variável por latitude e **não** são usadas para medir área.
- **Geometrias**: são achatadas para 2D e validadas (`make_valid`) apenas em
  cópias de trabalho; as saídas preservam a geometria original.
- **GeoPackage acima de ~2 GB**: pode ser recusado por leitores rígidos (ArcGIS)
  mesmo com o arquivo íntegro. Quando uma saída se aproxima disso, o programa
  avisa; a recomendação é dividir por tipo/origem.

## 9. Reprodutibilidade

A execução grava um relatório `relatorio_<UF>_<natureza>.json` com todos os
parâmetros usados, as contagens por etapa e o resultado da verificação de
conservação — de modo que qualquer execução seja auditável e reproduzível.
