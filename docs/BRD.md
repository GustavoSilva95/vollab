# BRD — Documento de Requisitos de Negócio

**Projeto:** VolLab — cockpit de decisão para traders de volatilidade em opções
**Base conceitual:** *Volatility Trading*, 2ª edição, Euan Sinclair
**Versão:** 1.2 — Fase 1
**Data:** 2026-11-22
**Status:** Aprovado (2026-11-22)

> **Histórico:** 1.0 (2026-11-21) aprovado. 1.1 (2026-11-22) incorpora os resultados da Etapa 0 ([relatório](./pesquisa/etapa-0.md), alterações A-01..A-10): COTAHIST como segunda fonte oficial da B3, regra de construção do OHLC, cadastro de séries pelo ISIN, feriados, proventos e questões QA-01, QA-02, QA-04, QA-05, QA-06 e QA-13 resolvidas. 1.2 (2026-11-22): mínimo de liquidez padrão elevado de 10 para **20 negócios no dia** (QA-06), por decisão do usuário.

---

## 1. Contexto e problema

Traders de opções pessoa física que operam volatilidade (venda/compra de vol, delta-hedge) no mercado brasileiro não dispõem de uma ferramenta integrada para:

- medir a volatilidade realizada (RV) e compará-la com a volatilidade implícita (IV);
- saber se existe **edge real**, líquido de custos e considerando a incerteza estatística;
- dimensionar posições de forma consistente com o edge e com o risco;
- acompanhar Greeks e risco da carteira durante a vida do trade;
- decidir se deve manter, sair ou rolar uma operação;
- registrar o histórico e comparar o previsto com o realizado.

Hoje essas decisões são tomadas sem medição sistemática. O VolLab será um **cockpit de decisão** que apoia o **antes, o durante e o depois** de cada trade. A plataforma **não executa ordens** e **não se integra a corretoras**: o trader executa na corretora e registra a posição manualmente.

## 2. Objetivos de negócio

| ID | Objetivo |
|----|----------|
| OB-01 | Responder, para cada ativo e cada trade candidato, se a IV está cara em relação à RV prevista, **com intervalo de confiança e líquido de custos**. |
| OB-02 | Padronizar a decisão de entrada em um semáforo de três estados: *sem edge*, *inconclusivo*, *edge líquido*. |
| OB-03 | Dimensionar posições pelo Kelly fracionado sobre o limite inferior do edge, limitado por um teto de perda por trade. |
| OB-04 | Acompanhar cada operação e a carteira (Greeks, stress, limites) e alertar quando regras de hedge, saída ou rolagem forem atingidas. |
| OB-05 | Manter um diário completo, com atribuição diária de P&L por Greek e comparação previsto vs. realizado. |
| OB-06 | Medir continuamente o erro de previsão de cada modelo de RV contra baselines. |

## 3. Princípios do produto

| ID | Princípio | Implicação |
|----|-----------|------------|
| PR-01 | **Edge medido, não só gráficos** | Toda tela de decisão apresenta um número de edge e um estado do semáforo, não apenas visualizações. |
| PR-02 | **Números líquidos de custos** | Edge, P&L esperado e ranking sempre descontam corretagem, emolumentos/taxas, spread estimado e custo de rebalanceamento do hedge. |
| PR-03 | **Incerteza estatística explícita** | Toda estimativa (RV prevista, prêmio de vol, salto de evento, edge) exibe intervalo de confiança. Amostra insuficiente gera "dados insuficientes", nunca um número sem lastro. |
| PR-04 | **Risco como parte do fluxo** | Dimensionamento, stress e limites são etapas obrigatórias do fluxo de entrada, não telas opcionais. |
| PR-05 | **Transparência de estimativas** | Valores estimados ou aproximados (spread, margem, IV de prazo constante indisponível etc.) são sempre rotulados como tal. |

## 4. Usuário e partes interessadas

| Papel | Descrição |
|-------|-----------|
| Usuário/Proprietário | Trader pessoa física de opções, nível intermediário a avançado, que opera volatilidade no mercado brasileiro. Na fase 1, **um único usuário**, uso próprio, **não comercial**. |
| Futuros usuários | Convidados, acessando por código de convite (**fora da fase 1**). |

## 5. Escopo

### 5.1 Dentro da fase 1

- Mercado: **Brasil (B3)**.
- Universo: **ativos-objeto escolhidos pelo usuário**, no máximo de 5 a 10.
- Estruturas: **straddle vendido, strangle vendido e venda coberta**.
- Delta-hedge: **com o próprio ativo-objeto**.
- Dados: **fechamento do dia anterior (D-1)**, com **entrada manual** de preços do momento (ativo-objeto e opção) para análise intradiária.
- Módulos:
  1. Dados e volatilidade
  2. Calendário de eventos (cadastro manual)
  3. Ranking de oportunidades entre os ativos cadastrados, com semáforo de edge
  4. Simulador de trades (payoff, Greeks, custos)
  5. Dimensionamento de posição
  6. Carteira e risco
  7. Gestão da operação (regras e alertas internos)
  8. Diário e performance
  9. Avaliação dos modelos de previsão de RV
- Execução **local**, sem autenticação.

### 5.2 Fora da fase 1

| Item | Observação |
|------|------------|
| Backtest e pesquisa de hipóteses | Fase 2 |
| Varredura do mercado inteiro (scanner amplo) | O ranking da fase 1 cobre só os ativos cadastrados |
| Importação de CSV de notas/corretora | Lançamentos manuais na fase 1 |
| Alertas externos (e-mail, push, mensageria) | Alertas apenas dentro da plataforma |
| Múltiplos usuários e acesso por convite | Quando a plataforma for hospedada |
| Hospedagem em nuvem | Começa local |
| Importação externa do calendário de eventos | Cadastro manual na fase 1 |
| Integração com corretoras e execução de ordens | Fora do escopo do produto |
| Outras estruturas (calendários, borboletas, ratios, compra de vol) | Fases futuras |
| Modelo de exercício antecipado (americanas) | Limitação conhecida (ver §13) |
| Cálculo de margem CORE da B3 | Margem informada manualmente |

## 6. Fluxo de valor: antes, durante e depois

```
ANTES                         DURANTE                          DEPOIS
─────                         ───────                          ──────
Ranking dos ativos            Marcação diária (D-1)            Encerramento da operação
  └ semáforo de edge          Greeks da posição e carteira     P&L final líquido (com IR)
Análise do ativo              Atribuição diária de P&L         Previsto vs. realizado
  └ IV, RV, eventos, skew     Alertas: hedge, saída,             └ RV prevista × realizada
Simulação do trade              rolagem, limites                 └ P&L esperado × final
  └ payoff, Greeks, custos    Stress tests                     Erro de previsão por modelo
Dimensionamento               Lançamentos de hedge,            Análise agregada de trades
  └ Kelly × teto                ajustes, exercício
Registro da entrada
```

## 7. Requisitos de negócio por módulo

Convenção: **RN** = regra de negócio; **RF** = requisito funcional de negócio.

### 7.1 Dados e volatilidade

**Coleta e armazenamento**

| ID | Requisito |
|----|-----------|
| RF-DAD-01 | Coletar diariamente os negócios do dia útil anterior para cada ativo-objeto cadastrado e cada série de opção relevante. |
| RF-DAD-02 | Gerar uma requisição de negócios por combinação **ticker × dia útil**, respeitando o calendário de pregões da B3. Para opções, só são pedidas as séries **elegíveis** (filtro de liquidez, §7.11) segundo o arquivo COTAHIST do mesmo pregão, que é baixado antes (1 requisição por pregão para o mercado inteiro). |
| RF-DAD-03 | Aceitar resposta em **CSV direto ou ZIP contendo um único arquivo de texto delimitado**; separador `;`; decimal com vírgula. ZIP só com cabeçalho = pregão **sem negócios** (status `vazio`); HTTP 404 = ticker inexistente. |
| RF-DAD-04 | Armazenar localmente todo dado baixado (cache), evitando repetir requisições e preservando o histórico caso a fonte mude ou seja descontinuada. |
| RF-DAD-05 | Carga inicial: **1 ano** de OHLC oficial do ativo-objeto (COTAHIST anual) e **3 meses** de negócios intradiários do ativo-objeto e das séries de opções elegíveis; daí em diante, acumular diariamente. |
| RF-DAD-06 | Rotina de carga disparada manualmente ou agendada localmente, com **relatório de falhas e lacunas** por ativo e data. |
| RF-DAD-07 | Cada fonte de dados fica isolada e substituível, sem afetar as regras de negócio. |

**Construção de séries**

| ID | Requisito |
|----|-----------|
| RN-DAD-01 | O OHLC diário do ativo-objeto vem do **COTAHIST oficial da B3**. Os negócios intradiários (ativo-objeto e opções) são considerados válidos pela **regra R4**: (1) apenas `DataNegocio = DataReferencia` e `TipoSessaoPregao = 1` (sessão regular); (2) todo `CodigoIdentificadorNegocio` que tenha uma linha com `AcaoAtualizacao ≠ 0` (cancelamento) é removido, inclusive a própria linha de cancelamento; (3) a ordem dos negócios é dada pelo `CodigoIdentificadorNegocio`, não pelo horário (negócios reemitidos levam o horário da correção). O OHLC reconstruído pela R4 é comparado com o oficial como **verificação de qualidade**; divergência de preço ou de nº de negócios gera alerta. (Validação: Etapa 0, 33/33 pares.) |
| RN-DAD-02 | O cadastro de séries (código, ativo-objeto, vencimento, strike, tipo call/put, estilo de exercício) vem do **COTAHIST** (fonte oficial da B3), que lista as séries negociadas em cada pregão. O **ativo-objeto é identificado pelo ISIN** (`CODISI`), nunca pelo prefixo do ticker (ex.: `PETR*` mistura PETR3 e PETR4). A **identidade de uma série é (código, vencimento)** com vigência, pois a B3 reutiliza códigos após o vencimento. O **estilo de exercício** é derivado do sufixo `E` do nome resumido (europeia); regra validada contra o Cadastro de Instrumentos oficial da B3 em 14.003/14.003 séries (Etapa 0). O cadastro oficial pode ser importado manualmente para conferência. |
| RN-DAD-03 | **Ajustes de strike e mudanças de código por proventos** (dividendos, JCP, bonificações etc.) devem ser refletidos no cadastro das séries e no histórico de cada uma. O ajuste é detectado pela mudança do strike da mesma série (código, vencimento) entre pregões no COTAHIST. |

**Volatilidade realizada**

| ID | Requisito |
|----|-----------|
| RF-VOL-01 | Calcular RV com múltiplos estimadores, no mínimo **close-to-close** e **Yang-Zhang**. |
| RN-VOL-01 | Anualização em **252 dias úteis**. |
| RN-VOL-02 | Rankings e percentis de volatilidade (ex.: IV rank, percentil de RV) são rotulados como **"relativos ao último ano"**. |

**Volatilidade implícita**

| ID | Requisito |
|----|-----------|
| RF-VOL-02 | Calcular a IV de cada negócio de opção com o modelo definido em RN-PRC-01. |
| RN-VOL-03 | **Sincronização temporal:** a IV de um negócio de opção usa o preço do **último negócio do ativo-objeto até o horário** do negócio da opção (campo `HoraFechamento`), e não o fechamento do dia. Pares com defasagem acima da **janela máxima (padrão 10 s, configurável)** são descartados e contados no relatório de qualidade. |
| RN-VOL-06 | **IV de referência diária** de cada série = **mediana das IVs por negócio, sincronizadas, na última hora da sessão regular**, com no mínimo 3 negócios. Abaixo disso, usa-se a IV do último negócio sincronizado, rotulada como **baixa amostra**. Guarda-se também o nº de negócios usados e o preço implícito. |
| RN-VOL-04 | Séries sem negócios no dia ficam sem IV naquele dia. Séries abaixo do filtro mínimo de liquidez (ver §15) são excluídas do smile e do cálculo de IV ATM. |
| RF-VOL-03 | **Scanner/ranking:** IV ATM de **prazo constante**, separando o **salto de eventos** (ex.: resultados) da vol "normal". |
| RN-VOL-05 | Se não houver **dois vencimentos com negócios ATM** para interpolar, a IV de prazo constante fica **indisponível** (sem extrapolação). Nesse caso exibe-se a IV ATM do vencimento disponível, rotulada com o prazo efetivo. |
| RF-VOL-04 | **Simulador:** usar a IV da **série real** operada, incluindo o skew. |
| RF-VOL-05 | Exibir smile/skew por vencimento e estrutura a termo da IV ATM. |

**Previsão de RV e avaliação de modelos**

| ID | Requisito |
|----|-----------|
| RF-PRV-01 | Prever a RV com **horizonte igual à vida da opção** analisada. |
| RF-PRV-02 | Modelos iniciais: médias ponderadas/**EWMA** e **combinação de estimadores** (close-to-close, Yang-Zhang). Candidatos: **GARCH** e outros. |
| RF-PRV-03 | Medir o **erro de previsão** de cada modelo, comparando com dois baselines: **RV close-to-close de 20 dias** e a **própria IV**. |
| RN-PRV-01 | A avaliação dos modelos usa **apenas observações não sobrepostas**. |
| RN-PRV-02 | Modelos sem amostra mínima de avaliação são exibidos como **"dados insuficientes"**. |
| RF-PRV-04 | Permitir escolher o modelo usado no cálculo do edge, exibindo sempre qual está em uso e seu histórico de erro. |

### 7.2 Precificação e convenções

| ID | Regra |
|----|-------|
| RN-PRC-01 | Modelo: **Black-Scholes europeu com dividendos discretos**. **Todas as opções são tratadas como europeias**; o exercício antecipado **não é modelado** (limitação conhecida, §13). |
| RN-PRC-02 | **JCP** é tratado como evento de provento, da mesma forma que dividendos, no ajuste do preço do ativo-objeto e no calendário. |
| RN-PRC-03 | Taxa livre de risco: **Selic** (série oficial do Banco Central, SGS) como aproximação inicial. |
| RN-PRC-04 | Convenção única para taxa, tempo e vol: **dias úteis / 252**, capitalização **exponencial**. Não misturar convenções. |
| RN-PRC-05 | Contagem de dias úteis pelo calendário de feriados da B3. |

### 7.3 Calendário de eventos

| ID | Requisito |
|----|-----------|
| RF-EVT-01 | Eventos da fase 1: **resultados trimestrais**, **datas ex-dividendo/ex-JCP** e **vencimentos de opções**. **Copom e eventos macro** como cadastro manual opcional. |
| RF-EVT-02 | Cadastro **manual**, com marcação **"confirmada"** ou **"estimada"**. |
| RN-EVT-01 | O **salto do evento** é estimado pela **estrutura a termo da IV** (vencimentos antes e depois do evento) e conferido com os **movimentos históricos do ativo em datas de resultado**. |
| RN-EVT-02 | Com pouco histórico, a estrutura a termo é a base da estimativa, e o intervalo de confiança do salto é exibido **largo**. |
| RN-EVT-03 | A vol "normal" usada na comparação IV × RV é a IV **sem o salto do evento**. |

### 7.4 Ranking de oportunidades e semáforo de edge

| ID | Requisito |
|----|-----------|
| RF-RNK-01 | Ranking **apenas entre os ativos cadastrados** pelo usuário, ordenado pelo estado do semáforo e pelo prêmio de vol líquido. |
| RF-RNK-02 | Para cada ativo, exibir: IV de prazo constante (ex-evento), RV prevista, **prêmio de vol com intervalo de confiança e líquido de custos**, IV rank (relativo ao último ano), skew, estrutura a termo, eventos próximos e indicadores de liquidez. |
| RN-EDG-01 | **Prêmio de vol** = IV − RV prevista, no mesmo horizonte. |
| RN-EDG-02 | Semáforo de três estados: |
| | • **Sem edge:** o limite superior do intervalo não supera os custos. |
| | • **Inconclusivo:** o intervalo contém o nível de custos. |
| | • **Edge líquido:** o **limite inferior do intervalo supera os custos**. |
| RN-EDG-03 | O estado "edge líquido" usa sempre a **versão mais conservadora** dos custos estimados, incluindo o spread. |
| RN-EDG-04 | O limiar de edge é **configurável** e deve ser **calibrado por dados** quando houver amostra suficiente. Até lá, vale o valor configurado, rotulado como "não calibrado". |
| RN-EDG-05 | **100% das entradas** registradas no diário passam pelo semáforo; o estado no momento da entrada é gravado com a operação. |

### 7.5 Custos

| ID | Regra |
|----|-------|
| RN-CST-01 | Custos incluídos no edge: **corretagem**, **emolumentos/taxas B3**, **spread estimado** e **custo dos rebalanceamentos do hedge**. |
| RN-CST-02 | Corretagem e taxas **configuráveis** pelo usuário. |
| RN-CST-03 | **Spread estimado** por regra configurável por **ativo e faixa de moneyness**, derivada da **dispersão dos negócios do dia**, com **piso configurável (mínimo = tick da B3)** e **sempre sinalizado como estimativa**. |
| RN-CST-04 | O **IR fica fora do edge** e entra **apenas no relatório de performance**, com alíquotas editáveis (padrão: **15% swing trade**, **20% day trade**). |

### 7.6 Simulador de trades

| ID | Requisito |
|----|-----------|
| RF-SIM-01 | Simular straddle vendido, strangle vendido e venda coberta, com séries reais da cadeia. |
| RF-SIM-02 | Exibir **payoff** no vencimento e em datas intermediárias, **Greeks** (delta, gamma, theta, vega) e **custos estimados**. |
| RF-SIM-03 | Aceitar **preços manuais** do ativo-objeto e da opção para análise com valores do momento, recalculando IV, Greeks e edge. Valores manuais são identificados como tais. |
| RF-SIM-04 | Gerar a **distribuição simulada de P&L** da estrutura, que alimenta o dimensionamento (RN-SIZ-02). |
| RF-SIM-05 | Exibir P&L esperado líquido de custos, incluindo o custo esperado do delta-hedge segundo a regra de hedge configurada. |

### 7.7 Dimensionamento de posição

| ID | Regra |
|----|-------|
| RN-SIZ-01 | Base de capital: **capital alocado para opções**, informado pelo usuário. |
| RN-SIZ-02 | **Kelly fracionado** com fração inicial de **1/4** (configurável), usando o **limite inferior do intervalo de edge** e a **variância da distribuição simulada de P&L** da estrutura, sem aproximação normal. |
| RN-SIZ-03 | **Teto de perda máxima por trade: 7% do capital** alocado (configurável). |
| RN-SIZ-04 | Tamanho final = **o menor** entre o Kelly fracionado e o teto. A tela mostra qual dos dois prevaleceu. |
| RN-SIZ-05 | Se o semáforo não estiver em "edge líquido", o Kelly resulta em zero; a plataforma não sugere tamanho positivo. |
| RN-SIZ-06 | **Margem** informada **manualmente** pelo usuário. Qualquer estimativa feita pela plataforma é rotulada como **aproximada**. |

### 7.8 Carteira e risco

| ID | Requisito |
|----|-----------|
| RF-RSK-01 | Greeks agregados da carteira e por ativo-objeto. |
| RF-RSK-02 | Exposição por vencimento. |
| RF-RSK-03 | Stress tests com valores configuráveis: |
| | • gap do ativo de **±10%**; |
| | • choque de **+10 pontos de vol**; |
| | • **queda do ativo combinada com alta de vol**; |
| | • **cenário de crise histórica**, aplicado de forma **paramétrica** (choques de preço e vol observados no ativo em episódios como mai/2017 e mar/2020, aplicados à carteira atual). |
| RF-RSK-04 | Limites configuráveis (ex.: perda em stress, vega total, concentração por ativo/vencimento) com alertas ao serem ultrapassados. |

### 7.9 Gestão da operação

Todas as regras abaixo são **parâmetros configuráveis** que disparam **alertas dentro da plataforma**, exibidos ao abrir ou atualizar.

| ID | Regra |
|----|-------|
| RN-GES-01 | **Hedge:** alerta quando o delta da posição sai da **banda configurada**; opcionalmente também por **intervalo de tempo**. |
| RN-GES-02 | **Saída, critério principal:** "**o edge acabou**", ou seja, a IV não supera mais a RV prevista líquida de custos. |
| RN-GES-03 | **Saída, critérios opcionais:** meta de lucro, stop e dias até o vencimento. |
| RN-GES-04 | **Rolagem** = fechamento + nova abertura. Só é sugerida se a **nova posição tiver edge líquido após custos** (incluindo os custos de fechar e abrir). Strike e vencimento de destino são configuráveis. |
| RN-GES-05 | Alertas de limites de carteira (RF-RSK-04). |

### 7.10 Diário e performance

| ID | Requisito |
|----|-----------|
| RF-DIA-01 | Registro manual de entrada, com estrutura, séries, quantidades, preços e custos reais, mais um retrato do momento da decisão: semáforo, edge, intervalo, RV prevista, modelo usado e tamanho sugerido vs. executado. |
| RF-DIA-02 | Cada **ajuste de hedge** é um **lançamento individual** com preço, quantidade e custos reais. |
| RF-DIA-03 | **Ajuste de strike, exercício e designação** são **tipos de lançamento próprios**, registrados manualmente e **ligados à posição original**. |
| RF-DIA-04 | **Atribuição diária de P&L** por **delta, gamma, theta, vega e resíduo**, marcada com o fechamento D-1. **O resíduo é sempre exibido.** |
| RF-DIA-05 | **Previsto vs. realizado** em dois níveis: **RV prevista × RV realizada** e **P&L esperado na entrada × P&L final**. |
| RF-DIA-06 | **Análise agregada** em muitos trades: distribuição dos erros, viés, acerto do semáforo e contribuição de cada Greek. |
| RF-DIA-07 | Relatório de performance líquido de custos e, separadamente, líquido de IR (RN-CST-04). |

### 7.11 Configurações

Todos os parâmetros citados como "configuráveis" ficam centralizados: custos, spread, limiares de edge, fração de Kelly, teto de perda, capital, cenários de stress, limites, regras de hedge, saída e rolagem, alíquotas de IR, metas de sucesso e filtros de liquidez. A plataforma registra **qual configuração estava vigente** em cada decisão gravada no diário.

## 8. Requisitos de dados

| Dado | Fonte (fase 1) | Observações |
|------|----------------|-------------|
| Negócios por ativo/série e data | B3: `GET https://drp.b3.com.br/rapinegocios/tickercsv/{ticker}/{data}?type=2` | D-1. Campos: `DataReferencia`, `CodigoInstrumento`, `AcaoAtualizacao`, `PrecoNegocio`, `QuantidadeNegociada`, `HoraFechamento` (`HHMMSSmmm`, horário de Brasília), `CodigoIdentificadorNegocio`, `TipoSessaoPregao`, `DataNegocio`, `CodigoParticipanteComprador`, `CodigoParticipanteVendedor`. Data e ticker consultados são metadados do arquivo baixado, não colunas da resposta. Endpoint sem documentação oficial: uso consciente, com cache. |
| Cotações diárias oficiais (COTAHIST) | B3: `https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_D{DDMMAAAA}.ZIP` (diário) e `COTAHIST_A{AAAA}.ZIP` (anual) | Arquivo oficial e público, layout fixo de 245 colunas. Fonte do **OHLC oficial** do ativo-objeto, do **cadastro das séries negociadas** e do **pré-filtro** da coleta de opções. |
| Cadastro de séries de opções | COTAHIST (RN-DAD-02) | Código, ISIN do ativo-objeto, vencimento, strike ajustado, tipo; estilo pelo sufixo `E` (validado). O Cadastro de Instrumentos da B3 exige reCAPTCHA e **não é automatizado**; importação manual opcional para conferência. |
| Taxa livre de risco | Banco Central (SGS), série da Selic | Convenção 252 dias úteis, exponencial. |
| Dividendos / JCP | Histórico: Yahoo Finance, conferido pelos ajustes de strike do COTAHIST. Futuros: **cadastro manual** | O Yahoo acerta as datas ex, mas os valores divergem do ajuste oficial (até 23%), não informa o tipo (dividendo × JCP) nem proventos anunciados e ainda não "ex". |
| Calendário de eventos | Cadastro manual | Confirmada/estimada. |
| Feriados B3 | Página oficial "Calendário de negociação — Feriados" da B3. Base de longo prazo: lista de feriados nacionais (2001–2078) fornecida pelo usuário, **complementada pelas regras da B3** (20/11 a partir de 2024, 24/12 e 31/12 sem pregão); anos ainda não publicados pela B3 ficam **provisórios** | Conferência posterior: pregão "útil" sem negócios gera alerta de calendário. 24/12 e 31/12 sem pregão; 25/01 e 09/07 com pregão. |
| Preços do momento | Entrada manual do usuário | Identificados como manuais. |
| Margem | Entrada manual do usuário | — |

## 9. Critérios de sucesso da fase 1

Os critérios medem **processo, não lucro**.

| ID | Critério | Meta (configurável) |
|----|----------|---------------------|
| CS-01 | Entradas que passaram pelo semáforo de edge | **100%** |
| CS-02 | Trades com atribuição de P&L completa | **N = 20** |
| CS-03 | Erro de previsão de cada modelo medido e comparado com os baselines (RV close-to-close 20 d e IV) | Todos os modelos ativos |
| CS-04 | Resíduo da atribuição | **< 15% da soma dos módulos das contribuições diárias** (\|delta\| + \|gamma\| + \|theta\| + \|vega\|), e não do P&L líquido |

> **Importante:** N = 20 **valida o processo**. **Não é evidência estatística de edge.** Conclusões sobre a lucratividade da estratégia exigem amostra muito maior e devem ser tratadas como hipóteses até lá.

## 10. Premissas

| ID | Premissa |
|----|----------|
| PM-01 | O endpoint da B3 continuará acessível e com o formato atual durante a fase 1. |
| PM-02 | O endpoint aceita tickers de opções individuais. **Validada na Etapa 0.** |
| PM-03 | Existe uma fonte oficial da B3 para o cadastro de séries, ou uma alternativa validável. **Validada na Etapa 0 (COTAHIST).** |
| PM-04 | A Selic é uma aproximação aceitável da taxa livre de risco nesta fase. |
| PM-05 | Black-Scholes europeu é aceitável como aproximação para todas as séries. |
| PM-06 | O usuário registra posições, hedges e eventos manualmente e com disciplina. |
| PM-07 | Decisões com dados D-1, complementados por preços manuais, atendem ao horizonte operacional do usuário. |

## 11. Restrições

- Sem integração com corretoras e sem execução de ordens.
- Fase 1 roda **localmente**, com **um único usuário**, sem autenticação.
- Uso pessoal e não comercial.
- Dados limitados a negócios realizados: **não há livro de ofertas (bid/ask)**.
- Uma requisição de negócios por ticker × dia útil, mais um arquivo COTAHIST por pregão.
- Histórico inicial: 1 ano de OHLC oficial (ativo-objeto) e 3 meses de negócios intradiários (ativo-objeto e opções elegíveis).
- Tecnologias conhecidas pelo proprietário: JavaScript, Next.js e React (orientação, não decisão de arquitetura deste documento).

## 12. Fases futuras (indicativo)

| Fase | Itens |
|------|-------|
| Fase 2 | Backtest e pesquisa com custos realistas; calibração do limiar de edge com mais histórico. |
| Posterior | Hospedagem; acesso por código de convite; múltiplos usuários; alertas externos; importação de CSV e de calendário; scanner amplo de mercado; novas estruturas; modelo para opções americanas. |

## 13. Limitações conhecidas

| ID | Limitação |
|----|-----------|
| LC-01 | **Exercício antecipado não é modelado**: IV e Greeks de séries americanas (em geral as calls de ações) podem divergir levemente. |
| LC-02 | O **spread é estimado**, não observado, por falta de bid/ask. |
| LC-03 | **Rankings e percentis** refletem apenas o **último ano**. |
| LC-04 | Com 1 ano de histórico e só observações não sobrepostas, a avaliação de modelos para horizontes de semanas terá **poucas observações** (cerca de 12 por ano para horizonte de ~21 dias úteis). A estimativa do GARCH tende a ser instável. |
| LC-05 | A IV vem de negócios isolados: séries ilíquidas geram smile incompleto e IV ruidosa. |
| LC-06 | Margem não é calculada pela plataforma (CORE B3 não é replicável com dados públicos). |
| LC-07 | O cenário de crise histórica é paramétrico, não uma reprodução da cadeia de opções da época. |
| LC-08 | Ajustes por proventos e eventos de exercício ou designação dependem de lançamento manual na fase 1. |

## 14. Riscos

| ID | Risco | Prob. | Impacto | Mitigação |
|----|-------|-------|---------|-----------|
| RS-01 | Descontinuação ou mudança do endpoint B3 | Média | Alto | Cache local de tudo o que for baixado; fonte isolada e substituível; monitorar falhas na rotina de carga. |
| RS-02 | Instabilidade ou bloqueio do Yahoo Finance; valores divergentes | Alta | Médio | Cadastro manual de proventos (obrigatório para os futuros); conferência pelos ajustes de strike do COTAHIST. |
| RS-03 | Ausência de fonte oficial para o cadastro de séries | Baixa | Alto | Resolvido na Etapa 0 com o COTAHIST; estilo de exercício validado contra o cadastro oficial. |
| RS-04 | Baixa liquidez gerando IV ruidosa e smile incompleto | Alta | Alto | Filtro de liquidez; IV de prazo constante indisponível quando não houver base; exibir incerteza. |
| RS-05 | Amostra pequena: intervalos largos e semáforo frequentemente "inconclusivo" | Alta | Médio | Comportamento **esperado, não defeito**; comunicar na interface; acumular dados diariamente. |
| RS-06 | Erros de lançamento manual no diário | Média | Alto | Validações de consistência (quantidades, posição resultante, vínculos com a posição original); resíduo alto da atribuição como sinal de erro. |
| RS-07 | Ajustes de strike por proventos não capturados | Média | Alto | Regra RN-DAD-03; tipo de lançamento próprio; alertar em datas ex-provento de ativos com posição aberta. |
| RS-08 | Volume de requisições na carga histórica de opções | Média | Médio | Pré-filtro pelo COTAHIST do pregão; carga incremental em várias sessões; limitar às séries elegíveis (vencimentos, moneyness e liquidez); respeitar ritmo de requisições. O serviço fica atrás do Cloudflare. |
| RS-09 | Excesso de confiança em poucos trades | Média | Alto | Aviso explícito (§9) de que N = 20 não é evidência de edge. |
| RS-10 | Divergência de IV em séries americanas | Baixa | Baixo | Limitação LC-01 documentada; revisar em fase futura. |

## 15. Questões em aberto

| ID | Questão | Sugestão inicial |
|----|---------|------------------|
| QA-01 | Qual fonte oficial da B3 fornece o cadastro de séries (código, ativo-objeto, vencimento, strike, tipo, estilo, ajustes)? | **Resolvida (2026-11-22):** COTAHIST (RN-DAD-02). |
| QA-02 | Qual fonte para o calendário de feriados da B3? | **Resolvida (2026-11-22):** página oficial da B3 + regra para anos não publicados (§8). |
| QA-03 | Qual **prazo** da IV de prazo constante usar no ranking? | 21 dias úteis, configurável. |
| QA-04 | Qual **preço de referência diário** de cada série para IV (último negócio, VWAP, mediana)? | **Resolvida (2026-11-22):** mediana das IVs sincronizadas na última hora (RN-VOL-06). VWAP descartado. |
| QA-05 | Qual **janela máxima** de defasagem entre o negócio da opção e o do ativo-objeto na sincronização (RN-VOL-03)? | **Resolvida (2026-11-22):** 10 s, configurável. |
| QA-06 | Quais são os **filtros mínimos de liquidez** (nº de negócios, quantidade, volume financeiro) por série? | **Resolvida (2026-11-22):** padrão **≥ 20 negócios no dia** (elevado de 10 na versão 1.2), K/S entre 0,9 e 1,1, 2 próximos vencimentos mensais, semanais desligadas; tudo configurável. |
| QA-07 | Qual **nível de confiança** e qual método para os intervalos? | 90%, configurável; método a definir. |
| QA-08 | Quais as **amostras mínimas** para sair de "dados insuficientes" em cada métrica? | Definir por métrica. |
| QA-09 | Como definir a **"perda máxima por trade"** em estruturas de perda ilimitada (straddle/strangle vendido) para aplicar o teto de 7%? | Usar a pior perda entre os cenários de stress configurados ou um percentil extremo (ex.: 99%) da distribuição simulada. |
| QA-10 | Qual método gera a **distribuição simulada de P&L** (bootstrap de retornos históricos, simulação paramétrica etc.)? | Bootstrap de retornos históricos, considerando a regra de hedge. |
| QA-11 | Quais **valores padrão** para banda de delta, intervalo de hedge, meta de lucro, stop e dias até o vencimento? | Definir com o usuário antes do uso. |
| QA-12 | Quais **choques exatos** do cenário de crise histórica (episódios e magnitudes)? | Medir nos episódios de mai/2017 e mar/2020 para cada ativo. |
| QA-13 | Como tratar os **cancelamentos** (`AcaoAtualizacao`) e os **tipos de sessão** (`TipoSessaoPregao`, ex.: leilão, after-market) na construção do OHLC e da IV? | **Resolvida (2026-11-22):** regra R4 (RN-DAD-01). |

## 16. Glossário

| Termo | Definição |
|-------|-----------|
| **ATM** | *At the money*: strike próximo do preço do ativo-objeto. |
| **Atribuição de P&L** | Decomposição do resultado diário em contribuições de delta, gamma, theta, vega e resíduo. |
| **Baseline** | Previsão de referência usada para avaliar os modelos (RV close-to-close de 20 d e a IV). |
| **D-1** | Dados do pregão do dia útil anterior. |
| **Delta-hedge** | Neutralização do delta da posição com compra/venda do ativo-objeto. |
| **Edge líquido** | Estado em que o limite inferior do intervalo de confiança do prêmio de vol supera os custos. |
| **EWMA** | Média móvel ponderada exponencialmente, usada na previsão de volatilidade. |
| **GARCH** | Família de modelos de volatilidade condicional. |
| **IV** | Volatilidade implícita, extraída do preço da opção. |
| **IV de prazo constante** | IV ATM interpolada para um prazo fixo, comparável ao longo do tempo. |
| **IV rank** | Posição da IV atual em relação ao seu intervalo no último ano. |
| **JCP** | Juros sobre capital próprio, tratado como provento. |
| **Kelly fracionado** | Fração do tamanho ótimo de Kelly, usada para reduzir risco de estimação. |
| **Observações não sobrepostas** | Janelas de avaliação que não compartilham dias, evitando inflar artificialmente a amostra. |
| **Prêmio de volatilidade** | IV − RV prevista no mesmo horizonte. |
| **Resíduo** | Parte do P&L não explicada pelos Greeks considerados. |
| **RV** | Volatilidade realizada, medida a partir dos preços do ativo-objeto. |
| **Salto de evento** | Variância adicional embutida na IV por um evento conhecido (ex.: resultado). |
| **Semáforo de edge** | Classificação em *sem edge*, *inconclusivo* ou *edge líquido*. |
| **Skew / smile** | Variação da IV entre strikes de um mesmo vencimento. |
| **Straddle / strangle vendido** | Venda de call e put no mesmo strike / em strikes diferentes. |
| **Venda coberta** | Venda de call com posse do ativo-objeto. |
| **Yang-Zhang** | Estimador de volatilidade que usa abertura, máxima, mínima e fechamento. |
