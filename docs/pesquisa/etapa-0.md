# Etapa 0 — Pesquisa e validação: relatório

**Versão:** 1.0
**Data:** 2026-11-22
**Base:** PRD §12, PLANO.md (Etapa 0)
**Situação:** Aprovado (2026-11-22). Alterações A-01..A-10 aplicadas no BRD 1.1 e no PRD 1.1. Universo inicial definido: BOVA11, BBAS3, PETR4 (carga ≈ 5,3 h).

---

## 0. Resumo executivo

| Item | Resultado | Muda escopo? |
|------|-----------|--------------|
| PM-02 — endpoint aceita opções | ✅ **Aceita.** 2 ativos × 5 séries × 3 datas, todos HTTP 200 com ZIP. | Não |
| PM-01 — endpoint acessível e estável | ✅ Acessível; formato documentado. Continuidade não pode ser provada (risco RS-01 segue). | Não |
| QA-13 — `AcaoAtualizacao` / `TipoSessaoPregao` | ✅ **Regra R4** reproduz o OHLC oficial em **33/33** pares ticker × pregão (11 pregões de PETR4). | Ajusta RN-DAD-01 |
| QA-01 — cadastro de séries | ⚠️ **COTAHIST** (arquivo oficial público da B3) serve de cadastro das séries negociadas; estilo de exercício é inferido. Arquivo de instrumentos completo exige reCAPTCHA. | **Sim** (nova fonte) |
| QA-02 — feriados | ✅ Página da B3 (2025–2026) + regra validada 25/25; 2027 provisório. | Não |
| QA-04 — preço de referência | ✅ Proposta: **mediana das IVs sincronizadas na última hora**. VWAP descartado. | Ajusta PRD §6.2 |
| QA-05 — janela de sincronização | ✅ Proposta: **10 s** (retém ~96% dos negócios). | Não |
| QA-06 — liquidez | ✅ Distribuição medida; limiares propostos. | Não |
| PRD-NF-04 — volume da carga | ❌ **Estimativa do PRD subestimada ~2×**: ~44 mil requisições de opções (~12 h), não 25 mil (7–8 h). | **Sim** |
| RS-02 — proventos no Yahoo | ⚠️ Datas corretas; **valores divergem** do ajuste oficial; sem tipo (dividendo/JCP) e sem proventos futuros. | Não (mitigação já prevista) |

**Recomendação:** seguir para a Etapa 1 **depois** de aprovar as alterações de BRD/PRD da §10, em especial a adoção do COTAHIST como segunda fonte da B3 (cadastro, OHLC oficial e pré-filtro da coleta).

---

## 1. Método

- Requisições a no máximo 1 req/s, `User-Agent` genérico, sem dados pessoais (PRD-NF-02). Total aproximado: 70 requisições ao `rapinegocios`, 6 arquivos COTAHIST, 1 ao SGS, 10 ao Yahoo.
- Datas usadas: pregões de 05 a 19/11/2026 e o feriado de 20/11/2026.
- Universo de exemplo (os 10 ativos com mais negócios em opções nos últimos 63 pregões): BOVA11, PETR4, BBAS3, VALE3, BBDC4, ITUB4, BEEF3, MGLU3, PRIO3, B3SA3. **O universo real do usuário ainda não foi informado**; os números de volume escalam com ele.
- Scripts descartáveis em [`scripts/`](scripts/) (stdlib Python, sem dependências). Fixtures e SHA-256 em [`fixtures/MANIFEST.csv`](fixtures/MANIFEST.csv).
- IVs desta pesquisa são **aproximadas** (BS europeu, sem dividendos, r = Selic 13,65% a.a.), usadas só para comparar candidatos entre si.

---

## 2. PM-01 / PM-02 — endpoint `rapinegocios`

`GET https://drp.b3.com.br/rapinegocios/tickercsv/{ticker}/{AAAA-MM-DD}?type=2`

| Caso | Resposta |
|------|----------|
| Ativo-objeto (PETR4, VALE3) | 200, `application/zip`, 0,3–0,7 MB compactado (3 MB de texto), ~0,8 s |
| Série de opção (PETRL44, PETRX44, PETRL501, VALEX603, VALEX623 + 12 outras) | 200, ZIP, 0,6–16 KB, ~0,25 s |
| Feriado (PETR4, 20/11/2026) | 200, ZIP com **apenas o cabeçalho** (207 bytes) → status `vazio`, não `falha` |
| Ticker inexistente (PETRL9999) | **404**, corpo vazio |

**Formato:** ZIP com **um único** arquivo `DD-MM-AAAA_NEGOCIOSAVISTA_RV_{TICKER}.txt` (nome também em `Content-Disposition`). Texto ASCII, separador `;`, decimal com vírgula, cabeçalho:

```
DataReferencia;CodigoInstrumento;AcaoAtualizacao;PrecoNegocio;QuantidadeNegociada;HoraFechamento;CodigoIdentificadorNegocio;TipoSessaoPregao;DataNegocio;CodigoParticipanteComprador;CodigoParticipanteVendedor
```

Divergências em relação ao BRD §11:
- Os campos `Data_Consulta` e `Ticker_Buscado` **não existem** na resposta. Eram, provavelmente, colunas acrescentadas por um script anterior. O engine deve registrá-los como metadados do `raw_file`.
- `HoraFechamento` vem como `HHMMSSmmm` em horário local de Brasília, sem zero à esquerda (ex.: `22944978` = 02:29:44.978).
- Cada arquivo traz, em geral, **um negócio com `DataNegocio` = pregão anterior** (madrugada). Ele deve ser excluído (ver §3).

**Limite de ritmo:** nenhum cabeçalho de rate limit e nenhum 429 em ~70 requisições a ≤ 1 req/s. O serviço fica atrás do **Cloudflare** (`cf-ray`, cookie `__cf_bm`), então pode haver desafios anti-bot se o ritmo subir. **Não fizemos teste de estresse, de propósito.** Manter 1 req/s e backoff (PRD-NF-02).

**Evidência:** `fixtures/b3/rapinegocios/` (45 arquivos).

---

## 3. QA-13 — cancelamentos e tipos de sessão

Observado em 11 pregões de PETR4 e 22 pares série/ativo × pregão:

| Campo | Valores vistos | Interpretação |
|-------|----------------|---------------|
| `AcaoAtualizacao` | `0` (novo), `2` (cancelamento) | `2` repete o `CodigoIdentificadorNegocio` do negócio cancelado, com o horário do cancelamento e sem participantes |
| `TipoSessaoPregao` | `1` (regular), `6` | `6` aparece em poucos negócios (18–77/dia, ex.: 13/11 e 19/11, dia de vencimento) e o OHLC oficial **não** os inclui. Semântica exata a confirmar; tratar como "fora da sessão regular" |
| `DataNegocio ≠ DataReferencia` | 1 linha por arquivo, com hora de madrugada | Negócio do pregão anterior, reapresentado. Excluir |

**Caso real de correção (06/11/2026, PETR4):** dois negócios em bloco (IDs 692280 e 692290, 800 mil e 1,2 milhão de ações, 17:52) foram cancelados com `AcaoAtualizacao=2` e **reemitidos** com IDs 692281 e 692291, quantidades menores e horário da correção (18:39). Ordenar por horário colocaria esses negócios como os últimos do dia e daria o fechamento errado (45,30 em vez de 45,36).

### Regra proposta (R4) para RN-DAD-01

1. Considerar apenas `DataNegocio = DataReferencia` e `TipoSessaoPregao = 1`.
2. Remover **todo** `CodigoIdentificadorNegocio` que tenha uma linha com `AcaoAtualizacao ≠ 0`. A linha de cancelamento também sai.
3. **Ordenar por `CodigoIdentificadorNegocio`**, não por `HoraFechamento`: abertura = menor ID, fechamento = maior ID.
4. Para sincronização intradiária (RN-VOL-03), usar `HoraFechamento` só nos negócios que sobrarem.

**Validação contra o COTAHIST oficial:** R4 reproduz número de negócios, abertura, máxima, mínima, fechamento e VWAP (±R$ 0,01) em **33/33** pares, incluindo os 11 pregões de PETR4 (05–19/11). A única divergência é a **quantidade** de 06/11: 47.069.700 contra 47.669.700 oficial (−1,3%), ligada à forma como o COTAHIST contabiliza a correção parcial. Ela não afeta preços nem volatilidade.

| Regra | Acertos |
|-------|---------|
| R0 — todas as linhas | 7/21 |
| R1 — só `DataNegocio = DataReferencia` | 19/21 |
| R3 — R1 + ação 0 + sessão 1, ordem por horário | 21/21 em 17–19/11, falha em 06/11 |
| **R4 — R3 + remoção de IDs cancelados + ordem por ID** | **33/33** (OHLC/n/VWAP) |

**Evidência:** `scripts/validate_ohlc.py` e `scripts/analyze.py qa13`, com saída reproduzível a partir das fixtures.

---

## 4. QA-01 / RS-03 — cadastro de séries

### Fontes avaliadas

| Fonte | Resultado |
|-------|-----------|
| **Instrumentos Cadastrados** (`arquivos.b3.com.br`, `InstrumentsConsolidated`) | A API de download exige **token de reCAPTCHA**. **Não deve ser automatizada.** Serve só como download manual eventual. |
| **COTAHIST** (`bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_{D|A}….ZIP`) | ✅ Oficial, público, sem captcha. Diário (~0,5 MB) e anual (~100 MB). Layout fixo de 245 colunas. |

### O que o COTAHIST oferece por série (opções `TPMERC` 070 = call, 080 = put)

Código (`CODNEG`), **ISIN do ativo-objeto** (`CODISI`), strike (`PREEXE`, já ajustado), vencimento (`DATVEN`), OHLC, preço médio, último, melhor oferta de compra/venda no fechamento (`PREOFC`/`PREOFV`), nº de negócios, quantidade, volume, fator de cotação, e o nome resumido (`NOMRES`) com marcadores.

### Validação

- **Letra do ticker ↔ (tipo, mês de vencimento):** consistente em **25.003/25.003** séries dos 10 ativos (A–L = calls jan–dez; M–X = puts jan–dez). Amostra de 25 séries listada na saída de `analyze.py`.
- **Estilo de exercício:** não há campo explícito. O sufixo **`E`** no `NOMRES` (`PETRE`, `VALEE`) aparece em **100% das puts** (12.431/12.431) e em parte das calls, o que é consistente com "E = europeia". **Inferência forte, ainda não confirmada em documento oficial**: tratar como `estilo_inferido` até ser conferida contra o arquivo de instrumentos (download manual) ou o layout oficial.
- **O prefixo do ticker NÃO identifica o ativo-objeto:** séries `PETR*` são de **PETR3 e de PETR4**. O ativo-objeto deve vir do `CODISI`, nunca do ticker (reforça RN-DAD-02).
- **Códigos são reutilizados** depois do vencimento, inclusive trocando de ativo-objeto (ex.: `PETRH48` venceu em 21/08/2026 como PETR3 e voltou como PETR4, vencimento 2028). **Identidade da série = (código, vencimento) com vigência**, não só o código.
- **Ajustes por provento (RN-DAD-03):** visíveis como queda do `PREEXE` na mesma série. Ex.: em 24/08/2026, 1.865 séries de PETR4 tiveram o strike reduzido em R$ 1,19. O `NOMRES` ganha marcadores (`/EJ`, `/ED`, `/EDJ`, `/EX`, `/ER`, `/AT`…). O código da série **não muda** nesses ajustes.
- **Semanais:** sufixo `W1`..`W5` no código (ex.: `PETRK498W1`).

**Limitação:** o COTAHIST só lista séries **negociadas** no dia. Para o VolLab isso basta, porque IV e ranking só usam séries com negócio. Séries sem negócio não entram na coleta de qualquer forma.

**Proposta (QA-01):** COTAHIST diário como fonte do cadastro, com estilo inferido e rotulado. Plano B para o estilo: importação manual do arquivo de instrumentos.

---

## 5. QA-02 — calendário de feriados

- **Fonte primária:** página oficial "Calendário de negociação — Feriados" da B3 (seção Listado B3). Publica **2025 e 2026; 2027 ainda não publicado** (consulta em 22/11/2026).
- **Conferência independente:** dias úteis sem pregão de PETR4 no COTAHIST 2025 e 2026 (até 19/11), mais o arquivo vazio de 20/11/2026. **Coincidem 100%** com a página.
- **Regra gerada** (feriados nacionais + Carnaval + Sexta-feira Santa + Corpus Christi pela Páscoa + 24/12 e 31/12 sem pregão) reproduz **25/25** dias publicados de 2025–2026.
- 25/01 e 09/07 (feriados de SP) **têm pregão**. 20/11 (Consciência Negra) **não tem**. Na Quarta-feira de Cinzas o pregão abre às 13h.

| Ano | Dias úteis sem pregão |
|-----|------------------------|
| 2025 (conferido) | 01/01, 03/03, 04/03, 18/04, 21/04, 01/05, 19/06, 20/11, 24/12, 25/12, 31/12 |
| 2026 (conferido até 20/11) | 01/01, 16/02, 17/02, 03/04, 21/04, 01/05, 04/06, 07/09, 12/10, 02/11, 20/11, 24/12, 25/12, 31/12 |
| 2027 (**provisório**, pela regra) | 01/01, 08/02, 09/02, 26/03, 21/04, 27/05, 07/09, 12/10, 02/11, 15/11, 24/12, 31/12 |

**Lista nacional fornecida pelo usuário** (`fixtures/calendario/feriados.csv`, 936 datas, 2001–2078): conferida contra os dias sem pregão de 2025–2026. **Não marca nenhum dia que teve pregão**, mas **não inclui 20/11, 24/12 e 31/12**, que a B3 fecha. Com esse complemento, reproduz 100% dos fechamentos observados e a lista de 2027 acima.

**Proposta:** `exchange_holidays` com `source` (`b3_oficial` | `regra`) e `confirmed`. Anos não publicados são gerados pela regra e marcados como provisórios. Toda coleta confere o resultado depois do fato (arquivo vazio em dia "útil" = alerta de calendário).

---

## 6. QA-04 / QA-05 — preço de referência e sincronização

Amostra: 17 séries de PETR4/VALE3 (dez/26 e jan/27, moneyness 0,9–1,1, de 13 a 1.632 negócios no dia), 6.619 negócios de opção em 19/11/2026.

### Defasagem opção → último negócio do ativo-objeto

| p50 | p90 | p95 | p99 | p99,9 |
|-----|-----|-----|-----|-------|
| 0,5 s | 6,3 s | 9,2 s | 15,9 s | 229 s |

### Candidatos de IV de referência (vol decimal, exemplos)

| Série | Último × fechamento do ativo (ingênuo) | Último sincronizado | VWAP × VWAP | Mediana sincronizada da última hora | σ intradiária |
|-------|------|------|------|------|------|
| VALEA591 | 0,3037 | 0,2886 | 0,2914 | 0,2931 | 0,0025 |
| PETRL14 | 0,3197 | 0,3127 | 0,3183 | 0,3132 | 0,0054 |
| VALEX710 | 0,2909 | 0,2909 | **0,2456** | 0,2899 | 0,0037 |
| VALEL614 | 0,3060 | 0,3060 | 0,2988 | 0,2865 | 0,0036 |

Saída completa: `scripts/sync.py`.

Conclusões:
- **Sem sincronização, o erro chega a 1,5 ponto de vol.** Confirma RN-VOL-03.
- **VWAP × VWAP é enviesado** (até −4,5 pontos), porque o preço da opção não é linear no ativo. **Descartado.**
- O **último negócio**, mesmo sincronizado, é sensível ao leilão de fechamento (VALEL614: 2 pontos acima da mediana).
- A **mediana das IVs por negócio, sincronizadas, na última hora** é estável e robusta a outliers.

### Propostas

- **QA-04:** IV de referência diária por série = **mediana das IVs por negócio, sincronizadas, na última hora da sessão regular**, com mínimo de 3 negócios. Abaixo disso, usar o último negócio sincronizado, rotulado como `baixa_amostra`. Gravar também o nº de negócios usados e o preço implícito (o preço que a IV de referência gera com o fechamento do ativo). O cálculo passa a ser **no espaço de IV**, não de preço.
- **QA-05:** janela máxima de defasagem de **10 s** (configurável). Pares fora dela são descartados e contados no relatório de qualidade.

---

## 7. QA-06 e PRD-NF-04 — liquidez e volume real da coleta

Janela: 63 pregões (20/08 a 19/11/2026), fonte COTAHIST.

### Distribuição de negócios por série-dia (todas as séries negociadas)

| Ativo | Séries-dia | Séries distintas | p25 | p50 | p75 | p90 |
|-------|-----------|------------------|-----|-----|-----|-----|
| BOVA11 | 56.490 | 3.911 | 2 | 9 | 65 | 337 |
| PETR4 | 51.581 | 3.946 | 2 | 6 | 28 | 119 |
| BBAS3 | 40.341 | 2.628 | 2 | 6 | 27 | 101 |
| VALE3 | 37.220 | 2.992 | 2 | 5 | 24 | 102 |
| ITUB4 | 27.391 | 2.447 | 2 | 5 | 20 | 58 |
| BBDC4 | 22.503 | 1.876 | 2 | 5 | 20 | 66 |
| MGLU3 | 20.236 | 1.754 | 2 | 4 | 13 | 36 |
| PRIO3 | 20.027 | 1.829 | 2 | 4 | 17 | 46 |
| B3SA3 | 15.078 | 1.381 | 2 | 4 | 15 | 42 |
| BEEF3 | 10.187 | 930 | 2 | 4 | 14 | 51 |

PETR4 tem ~820 séries negociadas **por dia** (muitas semanais). A metade das séries-dia tem ≤ 6 negócios.

### Requisições de opções na carga inicial (3 meses, 10 ativos) por cenário de filtro

| Cenário | Requisições | Séries/ativo/dia | Tempo a 1 req/s |
|---------|-------------|------------------|-----------------|
| Amplo: K/S 0,8–1,2, venc. ≤ 95 dias, ≥ 1 negócio | 169.992 | 270 | 47 h |
| K/S 0,8–1,2, ≤ 95 d, ≥ 20 negócios | 70.879 | 112 | 19,7 h |
| **A: K/S 0,9–1,1, 2 vencimentos mensais, ≥ 10 negócios** | **44.176** | **70** | **12,3 h** |
| B: K/S 0,9–1,1, 3 mensais, ≥ 5 | 54.824 | 87 | 15,2 h |
| C: K/S 0,85–1,15, 3 mensais, ≥ 10 | 63.882 | 101 | 17,7 h |
| PRD-NF-04 (estimativa original) | 25.000 | 40 | 7–8 h |

### Propostas

- **QA-06 — limiares padrão (configuráveis):** série elegível para IV com **≥ 10 negócios no dia**, **K/S entre 0,9 e 1,1** e **os 2 próximos vencimentos mensais**. Semanais ficam desligadas por padrão. O flag de liquidez é gravado em `option_daily_quotes`.
- **Pré-filtro pela COTAHIST do dia:** a lista de séries a baixar no `rapinegocios` sai do COTAHIST do mesmo pregão (1 requisição). Assim nunca se pede uma série sem negócio ou fora do filtro.
- **PRD-NF-04 revisado:** opções ≈ 44 mil requisições (~12 h); ativo-objeto ≈ 630 requisições (3 meses intradiários, ver §10). A carga inicial fica em **~12,5 h em várias sessões**. A coleta diária fica em **~700 requisições (~12 min)**.
- **Entrada para PRD-QA-02 (particionamento):** PETR4 tem 35–97 mil negócios/dia. Com 10 ativos × 3 meses intradiários são ~30 milhões de linhas, mais ~4–5 milhões de opções. Um ano intradiário do ativo daria ~125 milhões, o que reforça usar o COTAHIST para o OHLC de 1 ano (§10).

---

## 8. RS-02 — proventos via Yahoo Finance

Testado pela API de gráficos do Yahoo (`query1.finance.yahoo.com/v8/finance/chart/{T}.SA?events=div,split`), que é o mesmo backend usado pelo `yfinance`. A biblioteca em si não foi instalada nesta etapa, porque não há ambiente Python com dependências antes da Etapa 1.

Comparação com a **fonte oficial indireta**: reduções de strike das opções no COTAHIST 2026.

| Ativo | Datas ex (Yahoo × B3) | Valor Yahoo / ajuste B3 |
|-------|-----------------------|-------------------------|
| PETR4 | 3/3 coincidem | 0,6631/0,54 · 0,701/0,58 · 1,3481/1,19 (**+13% a +23%**) |
| VALE3 | 1/1 | 2,0307/1,76 (+15%) |
| BBAS3 | 4/4 | 0,2205/0,18 · 0,0701/0,06 · 0,1413/0,12 · 0,1053/0,11 |
| B3SA3 | 3/3 (+1 em 02/01, não observável no COTAHIST) | 0,0743/0,06 · 0,2212/0,18 · 0,2266/0,19 |
| MGLU3, BEEF3 | 1/1 | ≈ iguais |
| ITUB4, BBDC4 | coincidem (mensais pequenos somem no arredondamento do strike) | — |
| PRIO3, BOVA11 | nenhum evento nas duas fontes | — |

Lacunas do Yahoo:
1. **Valores divergem** do ajuste da B3 em até 23%. Hipótese: o Yahoo informa o valor bruto, e a B3 ajusta o strike pelo valor líquido de IR do JCP. **A confirmar.**
2. **Não informa o tipo** (dividendo × JCP), nem data com, nem data de pagamento.
3. **Não traz proventos anunciados e ainda não "ex"**, que são justamente os que importam para precificar a opção (RN-PRC-02).
4. Fonte não oficial e sem SLA (RS-02 segue com probabilidade alta).

**Proposta:** Yahoo como **candidato** para o histórico. O ajuste de strike do COTAHIST serve de conferência oficial de data e valor relevante para as opções. **Proventos futuros: cadastro manual no calendário** (já previsto no BRD), rotulados `estimado` ou `confirmado`.

---

## 9. Outras fontes verificadas

- **BCB SGS série 1178** (Selic anualizada base 252): 200, JSON `{"data":"DD/MM/AAAA","valor":"13.65"}` em **percentual**, que precisa ser convertido para decimal na ingestão (PRD §5.1). Sem valor em 02/11 (Finados): serve de conferência cruzada do calendário. Fixture em `fixtures/bcb/`.

---

## 10. Impacto em escopo e alterações propostas

> Nenhuma alteração foi aplicada ao BRD ou ao PRD. Elas dependem da aprovação do usuário (regra 4 do AGENTS.md).

| # | Documento | Alteração proposta | Origem |
|---|-----------|--------------------|--------|
| A-01 | BRD §11 (fontes), PRD §2 e §6 | **Adicionar o COTAHIST da B3** (diário e anual) como fonte oficial de: cadastro das séries negociadas, OHLC oficial do ativo-objeto e pré-filtro diário da coleta de opções. Novo adaptador em `data/b3_cotahist`. | QA-01, PRD-NF-04 |
| A-02 | BRD RN-DAD-01, RF-DAD-05 | OHLC diário do ativo-objeto **vem do COTAHIST** (1 ano = 1–2 arquivos anuais). Os negócios intradiários do ativo são coletados **só nos 3 meses** em que há opções, para sincronizar a IV. A reconstrução pela R4 vira **verificação de qualidade** (alerta se divergir). | QA-13, PRD-NF-04 |
| A-03 | BRD RN-DAD-01 | Incluir a regra **R4** (§3) para os negócios intradiários. | QA-13 |
| A-04 | BRD RN-DAD-02, PRD §6.1 | Ativo-objeto pelo **ISIN**, nunca pelo prefixo. Identidade da série = (código, vencimento) com vigência. Estilo de exercício `inferido` até confirmação. | QA-01 |
| A-05 | BRD §11 | Remover `Data_Consulta`/`Ticker_Buscado` dos campos da fonte (viram metadados do `raw_file`). Documentar 404 = ticker inexistente e ZIP só com cabeçalho = `vazio`. | PM-02 |
| A-06 | PRD §6.2 (`option_daily_quotes`) | Referência em **IV** (mediana sincronizada da última hora, mín. 3 negócios) + preço implícito + nº de negócios usados + status. | QA-04 |
| A-07 | PRD (config. padrão) | Janela de sincronização de 10 s; filtro de liquidez ≥ 10 negócios, K/S 0,9–1,1, 2 mensais, semanais desligadas. | QA-05, QA-06 |
| A-08 | PRD-NF-04 | Carga inicial de ~12,5 h em várias sessões (~45 mil requisições); diária de ~12 min (~700 req). | PRD-NF-04 |
| A-09 | PRD §6.1 (`exchange_holidays`) | Campos `source` e `confirmed`. Anos não publicados são gerados pela regra e marcados como provisórios. Alerta quando um dia "útil" vier vazio. | QA-02 |
| A-10 | BRD RS-02 / §11 | Yahoo apenas para o histórico, com conferência pelo ajuste de strike do COTAHIST. Proventos futuros manuais. | RS-02 |

## 11. Pendências e riscos abertos

| Item | Situação | Quando |
|------|----------|--------|
| Estilo de exercício (sufixo `E`) | Inferência forte, sem documento oficial | Confirmar com download manual do arquivo de instrumentos (o usuário baixa uma vez) ou layout oficial do COTAHIST — antes da Etapa 3 |
| Semântica de `TipoSessaoPregao = 6` | Excluído; OHLC confere sem ele | Investigar na Etapa 2 |
| Quantidade em correções parciais (06/11) | −1,3% vs oficial | Aceito; não afeta preços |
| Yahoo bruto × líquido | Hipótese | Etapa 2 (adaptador de proventos) |
| Calendário 2027 | Provisório | Atualizar quando a B3 publicar |
| Universo real de ativos do usuário | Não informado; volume calculado para um universo de exemplo | Antes da Etapa 2 |
| PM-01 (continuidade do endpoint) | Não demonstrável; cache e fonte isolada mitigam | Contínuo |
| Cloudflare na frente do `rapinegocios` | Sem bloqueio a 1 req/s | Monitorar na carga inicial |

## 12. Critérios de saída (PRD §12)

| Critério | Situação |
|----------|----------|
| PM-01/02: respostas reais ≥ 2 ativos e 5 séries em 3 datas | ✅ 2 ativos e 17 séries; 3 datas (+8 pregões de PETR4) |
| QA-01: fonte validada contra ≥ 20 séries ou plano B | ✅ COTAHIST, 25.003 séries consistentes, amostra de 25; estilo com plano B |
| QA-02: feriados 2025–2027 conferidos | ✅ 2025–2026 conferidos; ⚠️ 2027 provisório (não publicado pela B3) |
| QA-13: regras validadas contra o OHLC oficial de ≥ 1 ativo em 10 pregões | ✅ PETR4, 11 pregões (+22 pares) |
| QA-04/05: proposta com evidência | ✅ |
| QA-06: distribuição e limiares | ✅ |
| RS-02: testado, lacunas listadas | ✅ (via API do Yahoo; biblioteca `yfinance` na Etapa 2) |
| PRD-NF-04: estimativa refinada | ✅ ~12,5 h |
| Fixtures reais salvas | ✅ `docs/pesquisa/fixtures/` (8,5 MB; mover para `services/engine/tests/fixtures/` na Etapa 1). COTAHIST anuais **não versionados** (100 MB): URL + SHA-256 abaixo |

COTAHIST anuais usados (baixar de novo para reproduzir `analyze.py`; o CSV filtrado é gerado por `cotahist.py`):

| Arquivo | SHA-256 |
|---------|---------|
| `COTAHIST_A2025.ZIP` | `6cc0ad851c8f605ca30418acac48be81f1767f6ed05b4f563772d06ae448047d` |
| `COTAHIST_A2026.ZIP` (até 19/11/2026) | `f04c7606e7c5c71b874447ea04e2a4eb575f61ef9798f4205c030c22c056a4bf` |
