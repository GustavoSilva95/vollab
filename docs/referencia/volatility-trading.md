# Volatility Trading — Referência Técnica do Projeto

> **Fonte:** Euan Sinclair, *Volatility Trading*, 2ª ed. (Wiley, 2013), Caps. 1–15, a partir dos guias de estudo em português (com as notas do professor).
> **Público:** Claude Code e desenvolvedores da plataforma de apoio a traders de opções.
> **Status das fórmulas:** todas as fórmulas deste arquivo estão na **forma corrigida**. Onde o livro imprime algo errado, a versão correta está aqui e a divergência está listada na **Seção 2 (Errata)**. As implementações da **Seção 6** foram conferidas numericamente contra os exemplos do livro (casos de teste na **Seção 7**).

---

## Índice

0. [Como usar este arquivo](#0-como-usar-este-arquivo)
1. [Convenções e unidades](#1-convenções-e-unidades)
2. [Errata consolidada (livro → forma correta)](#2-errata-consolidada)
3. [Formulário e conceitos por capítulo](#3-formulário-e-conceitos-por-capítulo)
4. [Regras de decisão e heurísticas para a plataforma](#4-regras-de-decisão-e-heurísticas)
5. [Tabelas de referência numérica](#5-tabelas-de-referência-numérica)
6. [Implementação de referência (Python)](#6-implementação-de-referência-python)
7. [Casos de teste (valores esperados)](#7-casos-de-teste)
8. [Limitações, dados datados e adaptação ao mercado](#8-limitações-e-dados-datados)
9. [Glossário PT/EN](#9-glossário)

---

## 0. Como usar este arquivo

- **Ao implementar uma métrica**, procure a fórmula na Seção 3, confira a Errata (Seção 2) e use a implementação da Seção 6 como referência. Ao escrever testes, use os valores da Seção 7.
- **Ao desenhar uma funcionalidade** (alertas, *screeners*, relatórios, *sizing*, *hedge*), consulte a Seção 4: ela resume as regras práticas do autor.
- **Nunca** use a forma impressa no livro de uma fórmula listada na Errata.
- Onde este arquivo diz "**heurística**", trata-se de regra de bolso do autor, não de resultado matemático. Onde diz "**interpretação**", a definição não está no livro e foi inferida (pelo professor ou aqui); trate como configurável.
- Princípio-guia do livro para o software: **o BSM é para encontrar trades e comparar opções, não para medir risco.** Nunca estime risco extremo com o mesmo modelo usado para precificar (Cap. 1).

---

## 1. Convenções e unidades

| Item | Convenção usada aqui |
|---|---|
| Volatilidade, taxas, retornos | Fração decimal anualizada (0,30 = 30%). Exibir em % na UI. |
| "Pontos de vol" | 1 ponto = 0,01 de vol (ex.: 41 → 29 = 12 pontos). |
| Vega | O livro usa **vega por 1 ponto de vol** ("US$ 1.000 de vega" = P/L de US$ 1.000 por ponto). A função `bsm()` retorna vega por 1,00 de vol; **divida por 100** para "por ponto". |
| Retornos | **Logarítmicos**: $x_i = \ln(P_i/P_{i-1})$. |
| Anualização | Diário: ×252 na variância (×√252 na vol). Intradiário: ×(nº de períodos por pregão × 252). EUA: pregão de 6,5 h → 13 períodos de 30 min. |
| Tempo até o vencimento $T$ | Em anos. A CBOE (VIX) mede em **minutos**; para eventos (Cap. 5) o livro usa dias corridos/365. Ser consistente dentro de cada cálculo. |
| Média dos retornos | Em estimativas de vol, **zerar a média** (eq. 2.1b) salvo indicação contrária. |
| Curtose | Distinguir **curtose total** ($\mu_4$, normal = 3) de **curtose em excesso** ($\mu_4 - 3$). Excel `CURT/KURT` e `scipy.stats.kurtosis` (padrão) retornam **excesso**. Corrado-Su usa $(\mu_4 - 3)$. |
| Dividendos/splits | Ajustar a série **multiplicando** os preços anteriores à data *ex* por $1 - \text{div}/\text{preço}$ (ajuste para trás). Não subtrair (pode gerar preços negativos). |
| *Edge* | Medida **relativa**: $(\sigma_{impl} - \sigma_{prev})/\sigma_{prev}$ (Cap. 14). |
| *Haircut* | Exigência de financiamento da *clearing*. **Não é medida de risco** (Cap. 9). |

---

## 2. Errata consolidada

| Cap. | Onde | Impresso no livro | Forma correta (usar esta) |
|---|---|---|---|
| 2 | Eq. 2.15 (Garman-Klass) | termo de fechamento $\ln(c_i/c_{i-1})$ | Forma original de Garman-Klass (1980): $\ln(c_i/o_i)$ (abertura→fechamento). *Nota: este ponto não foi apontado no guia; confira no artigo original se necessário.* |
| 2 | Eq. 2.16 (Rogers-Satchell) | descreve $o_i$ como "fechamento" | $o_i$ = preço de **abertura** |
| 2 | Eqs. 2.17b/c (Yang-Zhang) | $\sigma_o$ com $\ln(o_i/o_{i-1})$; $\sigma_c$ com $\ln(c_i/c_{i-1})$ | $\sigma_o^2$: variância de $\ln(o_i/c_{i-1})$ (noite); $\sigma_c^2$: variância de $\ln(c_i/o_i)$ (pregão) |
| 2 | Eqs. 2.27/2.28 | escolha confusa da fórmula do 1º retorno | Nenhum retorno da série intradiária pode cobrir a noite; o 1º retorno do dia começa na **abertura** |
| 4 | Eq. 4.17 | chamada de "power utility" | É **utilidade exponencial** $U(W) \propto -e^{-\gamma W}$ |
| 5 | Eq. 5.9 | lado esquerdo $\sigma$ | Lado esquerdo é a **variância** $\sigma^2$ |
| 5 | Texto Corrado-Su | "a partir da equação 5.4" | Ajustar a partir da **Eq. 5.14** |
| 6 | Eq. 6.1 | sinal ambíguo | Arrow-Pratt: $r = -U''(W)/U'(W)$ |
| 7 | Eq. 7.15 | sem o fator ½ | $\tfrac12(\sigma_i^2 - \sigma_r^2)S^2\Gamma(\sigma_i)\,dt$ |
| 9 | Tabela 9.1 × texto p. 170 | "1% ao dia sobre o *haircut*" | ≈ **0,7%** ao dia (356,9 / 51.747) |
| 9 | Eq. 9.2 (Lo 2002) | $V = \frac{1}{\sqrt T}(1 + \tfrac12 SR^2)$ | **Variância** $= \frac{1}{T}(1 + \tfrac12 SR^2)$; **erro-padrão** $= \sqrt{(1+\tfrac12 SR^2)/T}$ ($T$ em anos, retornos IID) |
| 9 | Eq. 9.3 | "$\sigma_d \|I\|$" | Apenas $\sigma_d$ (*downside deviation*) |
| 9 | Fig. 9.8 / texto | trimestre com lucro de US$ 2.500.000 | Provavelmente **US$ 250.000** (coerente com a figura e as metas) |
| 9 | Cálculo do $z$ | "Equation 7.8" | **Eq. 9.8** |
| 9 | Hurst | "constante $a$ da Eq. 9.14" | A constante $a$ é da **Eq. 9.12**; com $a = 1/2$ obtém-se 9.14 |
| 10 | Eq. 10.2 | falta o 1 inicial | $x = 1 + q p^j + (j+1)(q p^j)^2 + \cdots$ (raiz de $1 - x + q p^j x^{j+1} = 0$ perto de 1) |
| 10 | Eq. 10.3 | expoente 5, último termo sem quadrado | $x \approx 1 + 0{,}45\cdot0{,}55^{8} + 9\,(0{,}45\cdot0{,}55^{8})^2 = 1{,}003896$ |
| 10 | Função valor (*prospect theory*) | "convexa para ganhos, côncava para perdas" | **Côncava nos ganhos, convexa nas perdas**, mais íngreme nas perdas |
| 10 | Dunning-Kruger | "David Denning" | **David Dunning**; artigo original de 1999 |
| 11 | Referência | Carr e Wu (2009) | Não consta da bibliografia (só Carr e Wu 2006). Provável: "Variance Risk Premiums", *RFS* 2009 — conferir |
| 12 | Eq. 12.2 | subscrito $V_{0_1,T}$ | $V_{0,T}$ |
| 12 | Eq. 12.5 | $\Delta X_i = (X_{i+1} + X_{i-1})/2$ | $\Delta X_i = (X_{i+1} - X_{i-1})/2$ (nas pontas: diferença simples para o vizinho) |
| 12 | Roll do VXX | $(1/30)\times 19{,}5 - 17{,}9 = 0{,}05$ | $(19{,}5 - 17{,}9)/30 \approx 0{,}053$ ponto/dia |
| 12 | VXZ | "o quarto e o sétimo futuros" | Cesta de futuros do **4º ao 7º** vencimento |
| 12 | IVTS | "Seção 12.2" | Seção *VIX Basis as a Predictor of the Futures* |
| 13 | Numeração | dois "(13.1)" | Mantida a do livro; o 2º (13.1) é $dL = L\lambda\,dS/S$ |
| 13 | Após 13.5 | compara com "Eq. 13.3" | Comparar com a **dinâmica (13.1)** $dL = L\lambda\,dS/S$ |
| 13 | Eq. 13.13 | $2\frac{L_0}{S_0}e^{-\sigma^2t}\int_c^\infty C(X)dX$ | Caso $\lambda=2$, $c=0$: $2\frac{L_0}{S_0^{\,2}}e^{-\sigma^2t}\int_0^\infty C(X)\,dX$ |
| 13 | Eq. 13.16 ($k^*$) | expoente $(\lambda - \lambda^2)$ | $k^* = \left(\frac{k}{L_0}e^{\frac{\lambda^2-\lambda}{2}\sigma^2t}\right)^{1/\lambda}$ |
| 13 | Eq. 13.18 (put, $\lambda>0$) | $+(\lambda-1)\int_0^{k^*}$ | $-(\lambda-1)\int_0^{k^*}$ (verificado numericamente; Seção 7) |
| 13 | Eq. 13.19 (put, $\lambda<0$) | $+(1-\lambda)\int_{k^*}^{0}$ com *puts*… | $-(1-\lambda)\int_{k^*}^{\infty} X^{\lambda-2}C_S(S_0X)\,dX$ (verificado numericamente) |
| 13 | Texto antes de 13.20 | "equação Z" | Eq. **13.6** com $L = L_0$ |
| 13 | Kelly do FXI | "alavancagem crítica 0,04" | 0,04 é o Kelly **ótimo**; crescimento zero no **dobro** (≈0,08). E há mistura de unidades (retorno mensal × vol anual) |
| 14 | Quadro diário | vega 25–26/jun e P/L de 2/jul | Erros de impressão; valores confiáveis: total final **US$ 18.390** e Tabela 14.2 |
| 5/14 | Corrado-Su, exemplos com "curtose 0" | — | O preço −0,21 do livro só se reproduz com $\mu_4 = 0$ **total** (excesso −3). Ver Seção 3, Cap. 5 |

---

## 3. Formulário e conceitos por capítulo

### Cap. 1 — Option Pricing (BSM como linguagem)

**Ideia central:** um modelo de opções é uma estrutura para **comparar** opções (*strikes*, vencimentos, ativos), traduzindo preços rápidos num parâmetro lento: a **volatilidade implícita**. Não precisa ser "verdadeiro", precisa ser útil e ter fraquezas conhecidas.

**P/L de uma carteira comprada em opção e delta-hedgeada num passo:**

$$\tfrac12(\Delta S)^2\,\Gamma \;+\; \theta \;-\; r\,(C - \Delta\,S) \tag{1.4}$$

Termos: gamma (ganho ∝ ½ do quadrado do movimento), theta (custo do tempo), financiamento.

**Equação BSM** (com $(\Delta S)^2 \approx \sigma^2S^2$ por unidade de tempo e sem lucro anormal):

$$\tfrac12\sigma^2S^2\Gamma + \theta - r(C - \Delta S) = 0 \tag{1.6}$$

**P/L de volatilidade:**

- Instantâneo: $\tfrac12 S^2\Gamma\,(\sigma_{real}^2 - \sigma_{impl}^2)$ (1.7)
- Total (forma preferida pelos traders): $\text{vega}\,(\sigma_{real} - \sigma_{impl})$ (1.8), válido **só em média**
- Relação gamma–vega: $\text{vega} = \sigma\,T\,S^2\,\Gamma$ (1.9)

**Propriedades-chave:**
1. O *drift* é neutralizado pelo hedge (no mundo contínuo).
2. O **tamanho** dos movimentos não é neutralizado: é o que gera o P/L.
3. Lucro de opção hedgeada é **path-dependent** (o gamma depende do *moneyness*).
4. BSM serve para **achar trades**, não para **controlar risco**.

**Ajustes de taxa no hedge** (modelados como "dividendo"):

| Situação | Taxa do hedge |
|---|---|
| Ativo com *dividend yield* $q$ | $r - q$ |
| *Commodity* com custo de armazenagem $q^*$ | $r + q^*$ |
| Futuro | 0 |
| Custo de aluguel para vender a descoberto | dividendo fictício adicional |

**Hipóteses do BSM e quão ruins são:** ativo negociável (liquidez!), venda a descoberto, taxa única e constante (rho pequeno em opções curtas), sem impostos (avaliar a opção pelo valor **para você**), tamanho qualquer, sem custos (Cap. 6), **vol constante** (falsa; é justamente o que se opera), **retornos normais** (falsa → *smile*), **sem saltos** (falsa → hedge com outras opções, *semi-static hedging*).

> "A volatilidade implícita é o número errado colocado na fórmula errada para obter o preço certo."

**Robustez relativa:** o *spread* entre duas opções próximas (ex.: *call* 50Δ vs 40Δ) é estimado com mais confiança que cada preço isolado.

**Risco de cauda:** nunca usar momentos gaussianos para risco extremo; sempre considerar cenários como "queda de 50%" mesmo sem precedente. Ferramentas: opções muito OTM, posições pequenas em relação à carteira.

---

### Cap. 2 — Volatility Measurement

**Variância amostral** ($x_i$ = log-retornos):

$$s^2 = \frac1N\sum (x_i - \bar x)^2 \tag{2.1a} \qquad s^2 = \frac1N\sum x_i^2 \;(\text{média zero; preferida}) \tag{2.1b}$$

$$\sigma^2 = \frac{N}{N-1}s^2 \tag{2.2}$$

**Viés de Jensen na vol** (retornos normais): $E[s] = b(N)\,\sigma$ com

$$b(N) = \sqrt{\frac2N}\,\frac{\Gamma(N/2)}{\Gamma((N-1)/2)} \tag{2.6}$$

válido para $s$ calculado com **1/N e média subtraída** (2.1a). Estimador sem viés: $s/b(N)$.

Para o estimador de **média zero** (2.1b, $s^2 = \frac1N\sum x_i^2$) o fator é outro: $b_0(N) = \sqrt{\frac2N}\,\frac{\Gamma((N+1)/2)}{\Gamma(N/2)}$ (0,9515 para N=5; 0,9876 para 20; 0,9975 para 100). Com média zero, a variância $\frac1N\sum x_i^2$ já é sem viés (não se perde grau de liberdade), então **não** se aplica $N/(N-1)$.

**Erro de amostragem** (o mais importante na prática):

$$\text{var}(s) \approx \frac{\sigma^2}{2N} \quad\Rightarrow\quad \text{SE}(s) \approx \frac{\sigma}{\sqrt{2N}} \tag{2.10}$$

Ex.: 30 fechamentos, σ = 30% → SE ≈ 3,9 pontos; IC 95% ≈ ±25% do valor verdadeiro. **30 fechamentos é amostra ruim.**

**Movimento diário típico ("regra do 20"):**

$$E|R| = \sqrt{2/\pi}\,\sigma_{dia} \;\Rightarrow\; \sigma_{anual} \approx 19{,}896\cdot\overline{|R|} \tag{2.11–2.12}$$

$$\text{movimento médio diário} \approx \frac{\sigma_{anual}\,S}{20} \tag{2.13}$$

(Não usar "16": isso confunde RMS com movimento típico.)

**Estimadores baseados em OHLC** ($o,h,l,c$ = abertura, máxima, mínima, fechamento; anualizar):

| Estimador | Fórmula (variância por período) | Eficiência vs CC | Viés / limitações |
|---|---|---|---|
| Close-to-close (CC) | $x_i^2$ | 1 | Sem viés após correção; converge devagar |
| Parkinson (1980) | $\frac{1}{4\ln2}\left(\ln\frac{h_i}{l_i}\right)^2$ | ~5× | Subestima (amostragem discreta, mercado fechado); não lida com drift nem saltos |
| Garman-Klass (1980) | $\tfrac12\left(\ln\frac{h_i}{l_i}\right)^2 - (2\ln2-1)\left(\ln\frac{c_i}{o_i}\right)^2$ | até ~8× | Viés para baixo maior que Parkinson; sem drift/saltos |
| Rogers-Satchell | $\ln\frac{h_i}{c_i}\ln\frac{h_i}{o_i} + \ln\frac{l_i}{c_i}\ln\frac{l_i}{o_i}$ | — | Lida com **drift**; não com saltos |
| Yang-Zhang (2000) | $\sigma_o^2 + k\sigma_c^2 + (1-k)\sigma_{rs}^2$ | até ~14× (simulação) | Lida com drift e **saltos de abertura**; vira CC se saltos dominam |

Yang-Zhang:

$$\sigma_o^2 = \text{Var}_{N-1}\!\left[\ln\tfrac{o_i}{c_{i-1}}\right],\quad \sigma_c^2 = \text{Var}_{N-1}\!\left[\ln\tfrac{c_i}{o_i}\right],\quad \sigma_{rs}^2 = \tfrac1N\textstyle\sum[\text{RS}_i],\quad k = \dfrac{0{,}34}{1{,}34 + \frac{N+1}{N-1}} \tag{2.17}$$

Razões de viés (variância estimada / verdadeira, por simulação):

| N | 5 | 10 | 20 | 50 | 100 | 200 |
|---|---|---|---|---|---|---|
| Parkinson | 0,55 | 0,65 | 0,74 | 0,82 | 0,86 | 0,92 |
| Garman-Klass | 0,38 | 0,51 | 0,64 | 0,73 | 0,80 | 0,85 |

Em dados reais (S&P 500, 5 min, 1988–2003) as correlações entre estimadores ficam entre 0,91 e 0,999. **Nenhum é "o melhor": calcular vários e ler as diferenças.** Ex.: Parkinson 40% e CC 20% → muita vol intradiária; fechamentos subestimam a vol real (útil para decidir o hedge).

**Estimador de *first exit time*** (corredor log de ±Δ; tempos de saída $\tau_i$):

$$E[\tau] = \frac{\Delta^2}{\sigma^2} \;\Rightarrow\; \sigma = \frac{\Delta}{\sqrt{\bar\tau}} \tag{2.18–2.19}$$

$$\text{Var}(\tau) = \tfrac23E[\tau]^2;\qquad E[f(\bar\tau)] \approx \sigma\left(1 + \frac{1}{4n}\right) \tag{2.21, 2.26}$$

Corrigir dividindo por $(1 + 1/(4n))$: fatores 0,800 (n=1), 0,952 (5), 0,976 (10), 0,995 (50). ~1,7× mais eficiente que CC com mesma quantidade de dados (Merrill 2011); robusto a ruído e saltos; ideal para tempo real; exige alta frequência.

**Alta frequência:**
- Intervalo recomendado: **15–30 min** (≫ tempo entre negócios). Abaixo de ~1 min domina o ruído de microestrutura (*bid/ask bounce*).
- **Ajuste da noite** (método do autor): calcular a vol só com retornos intradiários (sem cruzar a noite), anualizar, e **dividir pela fração da variância que ocorre no pregão** (medida comparando CC diário com abertura→fechamento). Típico: ações EUA ~85%, índices ~90%, ADRs ~60–70%.
- Padrão intradiário: pico na abertura, queda, leve alta no fechamento — irrelevante para opções de prazo > alguns dias.
- Para **previsão de longo prazo**, baixa frequência prevê alta melhor do que o contrário (Corsi 2009).

**Recomendações:** usar vários estimadores; escolher a janela equilibrando ruído (poucos dados) e irrelevância (dados velhos).

---

### Cap. 3 — Stylized Facts

1. **Vol não é constante**: *clustering* (autocorrelação forte de $|r|$ e $r^2$, quase nula de $r$), **memória longa**, **reversão à média** (média que muda devagar). Clustering é mais forte em mercados desenvolvidos e em baixas (mas decai mais rápido nelas e em *crashes*).
2. **Caudas grossas**: S&P 500 1950–2011, curtose em excesso 21,3; 19/out/1987 = −20,47% (prob. normal ~10⁻⁸⁸). Em ações, a maior parte da curtose está nos **retornos da noite** (resultados divulgados fora do pregão); petroleiras são exceção (estoques saem no pregão).
3. ***Leverage effect***: vol sobe quando o preço cai, assimetricamente. Forte em índices; vale para ativos com retorno esperado positivo; geralmente **não** em moedas. Quedas médias ~12–13% maiores que altas médias (SPY/QQQ 2000–2011).
4. **Volume × vol**: correlação forte (SPY 2011: volume × amplitude 0,85; × |retorno| 0,68). Usar volume ao menos como **filtro final** de sinais.
5. **Distribuição da vol ≈ log-normal**, assimétrica à direita (muito tempo em vol baixa, picos raros). Mediana da vol 30d do S&P: **21,6%** abaixo da MM200 vs **12,1%** acima.

**Teste de razão de variância:** vol medida com retornos diários > com retornos mais longos ⇒ reversão à média. VIX (1990–2011): 0,96 diário, 0,84 semanal, 0,59 mensal.

---

### Cap. 4 — Volatility Forecasting

**Por que é previsível:** clustering + reversão à média. O mercado de opções falha as três condições de Fama (custos altos, informação privilegiada, discordância sobre a informação).

**Janela móvel:** boa medida do passado, má previsão (outliers entram e saem abruptamente).

**EWMA:** $\sigma_t^2 = \lambda\sigma_{t-1}^2 + (1-\lambda)r^2$, λ ∈ [0,9; 0,99] (4.1). Críticas: só disfarça outliers (melhor decidir conscientemente excluir eventos únicos como resultados, salvo se o período previsto contiver outro) e **ignora reversão à média** (previsão plana).

**GARCH(1,1):**

$$\sigma_t^2 = \omega + \alpha r_{t-1}^2 + \beta\sigma_{t-1}^2,\qquad V = \frac{\omega}{1-\alpha-\beta} \tag{4.4–4.5}$$

$$E[\sigma_{t+\tau}^2] = V + (\alpha+\beta)^\tau(\sigma_t^2 - V) \tag{4.9}$$

EWMA = GARCH com $\omega=0$, $\alpha = 1-\lambda$, $\beta = \lambda$. Ex. MSFT 2003–2007: ω = 5,05e-6, α = 0,053, β = 0,884 → vol LP ≈ 14%.
Limitações: só estruturas a termo monotônicas (não "corcundas"); log-verossimilhança plana (usar *variance targeting*: $\omega = \hat\sigma^2_{amostra}(1-\alpha-\beta)$); precisa de ≥ ~1.000 pontos; escala natural diária; parâmetros instáveis. Variantes: EGARCH, GJR (assimétricos), IGARCH (α+β=1), TGARCH, AGARCH, CGARCH (memória longa).

**Log-verossimilhança GARCH (maximizar):** $\sum_i\left(-\ln\sigma_i^2 - r_i^2/\sigma_i^2\right)$ (4.15).

**O trader precisa da distribuição, não de um número.** Usar **cones de volatilidade** (Burghardt-Lane): para horizontes de 20/40/60/120/240 dias, registrar máx, p75, mediana, p25, mín. Com janelas sobrepostas, multiplicar a **variância** por

$$m = \frac{1}{1 - \frac hn + \frac{h^2-1}{3n^2}},\quad n = T - h + 1 \tag{4.16}$$

(ex.: h = 60, T = 1.006 → m ≈ 1,066 na variância, ≈ 1,03 na vol).

Heurística: vender implícita de 1 mês a 35% porque está no **percentil 90** do cone é um plano sensato; vender porque "o GARCH prevê 20%" é menos.

**Contexto de mercado:** comparar o *spread* implícita/realizada da ação com o do índice em termos **relativos** (Citi 39/26 = 1,50 vs S&P 24/18 = 1,33). Usar o *spread* do índice como **vantagem mínima exigida**.

**Informação fundamentalista** (Sridharan 2012): o mercado **subestima** vol de empresas com alto P&D, fluxo de caixa volátil, gerenciamento de resultados; **superestima** de empresas grandes, ROA alto e **alta alavancagem**. Melhor para vol **relativa** e prazos longos.

**Prêmio de variância:** implícita costuma ser ≥ prevista (30% acima é comum; o contrário quase nunca). Razões: venda de seguro, eventos possíveis ainda não ocorridos, microestrutura (*market makers* cotam ligeiramente alto). **Não implica que vender sempre dá lucro.** Uso correto: **subtrair o *spread* normal** antes de julgar se a opção está cara. S&P: VIX − vol CC 30d ≈ **3,09 pontos** em média.

**Bakshi-Madan (2006)** (utilidade exponencial, aversão γ):

$$\frac{\sigma_{rn}^2 - \sigma^2}{\sigma^2} \approx -\gamma\sigma\cdot\text{skew} + \frac{\gamma^2}{2}\sigma^2(\text{kurt} - 3) \tag{4.18}$$

(kurt total). Ex. 3/ago/2012: SPY → γ ≈ 6,4; aplicado ao EEM → implícita justa 0,221 vs 0,225 de mercado. Contradito pelos dados: o *spread* percentual **cai** quando o VIX sobe (tabela na Seção 5).

---

### Cap. 5 — Implied Volatility Dynamics

**PCA da superfície** (Alexander 2001): deslocamento paralelo **65–80%**, inclinação 5–15%, curvatura ~5%. **Priorizar o nível ATM**, depois a inclinação.

**Reversão à média — definição operacional:** retornos com autocorrelação negativa (VIX: −0,04 diário, −0,21 semanal, −0,12 mensal) e/ou lucratividade de estratégias contrárias (Bollinger 2σ sobre EWMA no VIX: 62,2% de acerto, ganho médio 1,05 vs perda 0,93 ponto). Modelo: $R_t = \rho(R_{t-1}-\mu) + \mu + \sigma Z_t$ (5.1).

**Resultados trimestrais:**
- Comprar *straddle* do 1º vencimento 10 dias antes e vender na véspera: 43% de acertos, ganho/perda 1,70, assimetria +5,4.
- Vender na véspera e recomprar no dia seguinte: 64% de acertos, ganho/perda 0,69, assimetria −2,1.
- **Filtro útil nos dois:** alta **dispersão das estimativas dos analistas** = (maior − menor)/média. P/L, valor de mercado, *yield* e nº de analistas não ajudam.
- Vale para outros mercados (juros antes de dados macro, *commodities* antes de relatórios).

**Vol a termo e salto implícito de um evento** (1º vencimento $\sigma_1,T_1$; 2º $\sigma_2,T_2$; se $\sigma_1 \le \sigma_2$ não há salto precificado):

$$\sigma_{12} = \sqrt{\frac{\sigma_2^2T_2 - \sigma_1^2T_1}{T_2 - T_1}} \tag{5.2}$$

$$\sigma_E = \sqrt{T_1(\sigma_1^2 - \sigma_{12}^2)} = \sqrt{(\sigma_1^2 - \sigma_2^2)\frac{T_1T_2}{T_2 - T_1}} \tag{5.3}$$

$$E|R_{evento}| = \sqrt{2/\pi}\;\sigma_E \tag{5.4}$$

**Dinâmica do *smile*:** *sticky strike* (vol por strike fixa; mercado lateral) vs *sticky delta* (vol por delta fixa; mercado em tendência) (Derman 1999). Ambas geram arbitragem se valessem sempre. Usar uma "espinha dorsal" decrescente no strike, com inclinação escolhida pelo trader. **Delta total**:

$$\frac{dC}{dS} = \Delta_{BSM} + \text{vega}\,\frac{\partial\sigma}{\partial S} \tag{5.8}$$

**Por que existe *smile*:** demanda de proteção (puts), venda coberta de calls, prêmio de aquisição (strikes altos), hedge dos *market makers* (autorrealizável), **correlação em índices**, retornos não normais. Todos menos o último são pressão de oferta/demanda → o formato tende a um **equilíbrio estável por produto**.

Variância de índice:

$$\sigma_I^2 = \sum_i w_i^2\sigma_i^2 + 2\sum_{i<j}w_iw_j\rho_{ij}\sigma_i\sigma_j \tag{5.9}$$

**Normalização prática do *smile*:** indexar por **delta** e dividir cada vol pela **ATM** do mesmo vencimento → curva muito estável no tempo (QQQQ: 10Δ put ≈ 1,47; 10Δ call ≈ 0,77–0,79 em todos os vencimentos). Desvios desse equilíbrio são sinais.

**Momentos amostrais:** $\mu_3 = \frac{\frac1N\sum(x-\bar x)^3}{\sigma^3}$, $\text{Var}(\mu_3)\approx 6/N$; $\mu_4 = \frac{\frac1N\sum(x-\bar x)^4}{\sigma^4}$, $\text{Var}(\mu_4)\approx 24/N$ (muito ruidosos).

**Corrado-Su (1996)** — call europeia com assimetria e curtose (expansão de Gram-Charlier nos **retornos**):

$$C = C_{BSM} + \mu_3Q_3 + (\mu_4 - 3)Q_4 \tag{5.14}$$

$$Q_3 = \tfrac16S\sigma\sqrt T\left[(2\sigma\sqrt T - d_1)\,n(d_1) + \sigma^2T\,N(d_1)\right] \tag{5.15}$$

$$Q_4 = \tfrac1{24}S\sigma\sqrt T\left[(d_1^2 - 1 - 3\sigma\sqrt T d_2)\,n(d_1) + \sigma^3T^{3/2}N(d_1)\right] \tag{5.16}$$

$d_1, d_2$ do BSM; put por paridade $P = C - S + Ke^{-rT}$. Calibrar $(\sigma,\mu_3,\mu_4)$ **por vencimento** minimizando a soma dos quadrados dos erros de preço. Ex. GME out/2007: σ = 0,508, μ₃ = −0,701, μ₄ = 4,42.
Cuidados: σ ≠ vol ATM; efeitos de μ₃ e μ₄ sobre a curva se misturam; **preços negativos são possíveis** — o exemplo do livro (S=50, K=65, 50 dias, r=5%, σ=50%, μ₃=−0,7, **μ₄=0 total**) dá −0,21; restringir à região válida (Jondeau-Rockinger). Só europeias (para americanas: árvores de Edgeworth/Gram-Charlier).

**Estrutura a termo (Stein 1989):** vencimentos longos **sobrerreagem** a mudanças no curto. Constante teórica ~0,85, observada ~0,95:

$$\sigma^l - \langle\sigma\rangle \approx c\,(\sigma^s - \langle\sigma\rangle),\quad c_{teórico}\approx0{,}85$$

Ex.: média 0,15, curto 0,25 → longo justo 0,235; mercado 0,245.

---

### Cap. 6 — Hedging

**Objetivo do hedge:** remover riscos indesejados (direção) **ao menor custo**. Se está operando direção, não está hedgeando. Hedge contínuo é impossível e teria custo infinito; o *bid/ask* impede delta exatamente zero.

Exemplo (Tabela 6.1): vendido 1.000 vega, implícita 50% vs realizada 40%, *spread* do ativo US$ 0,10: lucro médio 9.791 (semanal), 9.220 (diário), 8.830 (2×/dia), 7.952 (5×/dia).

**Utilidade exponencial** $U(W) = -e^{-\gamma W}$, Arrow-Pratt $r = -U''/U' = \gamma$. Equivalente certo $W_0 = \mu - \tfrac12\gamma\sigma^2$ ⇒ $\gamma = 2(\mu - W_0)/\sigma^2$ (6.6). Ex.: μ = 10.000, σ = 2.000, EC = 8.000 → γ = 0,001.

**Hodges-Neuberger (ótimo, impraticável em tempo real):** banda de não-negociação em torno do delta; fora dela, ajustar **só até a borda**. Propriedades: banda **mais estreita quando vendido** em gamma; centro ≠ delta BSM (delta "em S"); largura cresce com custo e cai com aversão ao risco.

**Leland** (custo proporcional por operação λ = meio *spread*, intervalo Δt em anos):

$$\hat\sigma_{comprado} = \sigma\sqrt{1 - \frac\lambda\sigma\sqrt{\frac{8}{\pi\Delta t}}},\qquad \hat\sigma_{vendido} = \sigma\sqrt{1 + \frac\lambda\sigma\sqrt{\frac{8}{\pi\Delta t}}} \tag{6.7–6.8}$$

Ex.: vol justa 10%, *spread* 1% (λ = 0,5%), hedge diário (Δt = 1/365) → precisa vender acima de **15,9%**. Usar **antes do trade** para estimar quanto do edge o hedge consome.

**Whalley-Wilmott** (aproximação; fácil de implementar):

$$\Delta = \frac{\partial V}{\partial S} \pm \left(\frac32\,\frac{e^{-r(T-t)}\lambda S\Gamma^2}{\gamma}\right)^{1/3} \tag{6.9}$$

Perde a assimetria comprado/vendido e centra no delta BSM.

**Zakamouline** (melhor aproximação prática de HN):

$$\Delta = \frac{\partial V(\sigma_m)}{\partial S} \pm (H_0 + H_1),\qquad \sigma_m^2 = \sigma^2(1 - K) \tag{6.11–6.12}$$

$$H_0 = \frac{\lambda}{\gamma S\sigma^2T},\quad H_1 = 1{,}12\,\lambda^{0{,}31}T^{0{,}05}\left(\frac{e^{-rT}}{\sigma}\right)^{0{,}25}\left(\frac{|\Gamma|}{\gamma}\right)^{0{,}5},\quad K = -4{,}76\,\frac{\lambda^{0{,}78}}{T^{0{,}02}}\left(\frac{e^{-rT}}{\sigma}\right)^{0{,}25}(\gamma S^2|\Gamma|)^{0{,}15} \tag{6.13–6.15}$$

($T$ = prazo remanescente; Γ da **carteira**; K < 0 ⇒ σ_m > σ.) Domina os demais em custo para o mesmo risco na maioria dos níveis.

**Armadilha:** ativo "picotado" — aumentar **vol** estreita a banda (mais hedge); aumentar **custo** alarga (menos hedge). Estimar separadamente: custo pela diferença execução vs negócio anterior; vol num período com muitos negócios.

**Gamma que muda de sinal** (ex.: *butterfly*): considerar o perfil global; preferir **hedge estático com opções** quando barato.

**Risco de saltos:** comprar asas quando vendido ATM, diversificar, dimensionar, não tratar o pior histórico como o pior possível.

**Impacto de mercado (Gatheral):** em "tempo de negociação", impacto $F(n) = \alpha\sqrt n$ e

$$\sigma_t^2 = \alpha^2\mu_t \;\Rightarrow\; \alpha = \frac{\sigma_t}{\sqrt{\mu_t}} \tag{6.21–6.22}$$

($\mu_t$ = volume por unidade de tempo). Não distingue compra/venda; ignora estoque do *market maker*.

**Agregação por índice** (beta β, preços $S_A$, $S_I$):

$$\Delta_I = \beta\frac{S_A}{S_I}\Delta_A,\qquad \Gamma_I = \beta^2\frac{S_A^2}{S_I^2}\Gamma_A,\qquad \text{beta de vol} \approx \beta \;(\sigma_A^2\approx\beta^2\sigma_I^2) \tag{6.23, 6.26, 6.27}$$

Abordagem conservadora: bandas por ativo **e** monitorar risco agregado em índices.

---

### Cap. 7 — Distribution of Hedged Option Positions

$P/L = \text{Vega}(\sigma_{impl} - \sigma_{real})$ (vendedor) vale **só em média**. Com implícita = realizada = 30%, hedge diário, 10 simulações: de −1.741 a +1.984.

**Dispersão do P/L por hedge discreto** (Kamal-Derman 1999), N = nº de rehedges, vega por ponto, σ em pontos:

$$\sigma_{P/L} \approx \sqrt{\frac\pi4}\;\text{Vega}\;\frac{\sigma}{\sqrt N} \tag{7.7}$$

Tabela 7.1 (1.000 vega, 1 ano, 30%): desvio-padrão 2.615 (diário) e 5.715 (semanal); razão ≈ √(252/52). Saltos **não** se resolvem com mais hedge.

**Aproximações ATM** (Brenner-Subrahmanyam): $C \approx \frac{1}{\sqrt{2\pi}}S\sigma\sqrt T$ (7.8); vega do *straddle* $\approx \frac{2}{\sqrt{2\pi}}S\sqrt T$ (7.9); *straddle* sem hedge: $\sigma_{P/L} \approx \frac{1}{\sqrt2}S\sqrt T\sigma$ (7.10).

**Com que vol fazer o hedge** (vendido a $\sigma_i$, realizada $\sigma_r$):

- **Hedge na realizada:** P/L final mais certo, caminho muito ruidoso (termo estocástico):
$$\tfrac12(\sigma_i^2 - \sigma_r^2)S^2\Gamma(\sigma_i)dt + (\Delta(\sigma_i) - \Delta(\sigma_r))\big((\mu - r)S\,dt + \sigma S\,dX\big) \tag{7.14}$$
- **Hedge na implícita:** caminho suave e determinístico, resultado final mais incerto (depende do gamma acumulado):
$$P/L = \tfrac12(\sigma_i^2 - \sigma_r^2)\int e^{-rt}S^2\Gamma(\sigma_i)\,dt \tag{7.15–7.16}$$

Ganha-se mais quando o ativo fica **perto do strike** (gamma alto). Argumento para *strangles*/*strips* e para *break-even skews* (Dupire).

**Tabela 7.3 — viés da vol de hedge:**

| Posição | Mercado em tendência | Mercado lateral |
|---|---|---|
| Vendido em gamma | vol **baixa** | vol **alta** |
| Comprado em gamma | vol **alta** | vol **baixa** |

Simulações: OTM tem muito mais variância de P/L que ATM; errar a vol de hedge **para cima** gera menos variância.

---

### Cap. 8 — Money Management

**Princípio:** o *sizing* não cria edge, mas pode destruir um trade bom. Definir esquema e parâmetros **antes** de operar.

**Kelly binário** (ganho $w$ com prob. $p$; perda $l$ com prob. $q$):

$$f^* = \frac{pw - ql}{wl} \tag{8.5}$$

**Kelly contínuo, edge pequeno:**

$$f^* = \frac{r}{\sigma^2}\quad(r = \text{retorno em excesso esperado}) \tag{8.14}$$

**Crescimento com fração $f$ do Kelly:** $GR = (f - f^2/2)\,r^2/\sigma^2$ (8.15); máximo $r^2/(2\sigma^2)$ em f = 1; **zero em f = 2**; simétrico (0,7 ≡ 1,3 em crescimento, menos risco abaixo).

**Prob. de atingir B× antes de A×** (fração f do Kelly):

$$P(A,B) = \frac{1 - A^{1-2/f}}{B^{1-2/f} - A^{1-2/f}} \tag{8.17}$$

Dobrar antes de cair pela metade: 0,667 (Kelly cheio), 0,739 (0,8), 0,834 (0,6), 0,941 (0,4), 0,998 (0,2).

**Por que Kelly fracionado:** meio-termo retorno/volatilidade e "Bayes do pobre" (½ Kelly ≈ média entre seu edge e edge zero). Erro de estimativa: $\bar p = (w+1)/(N+2)$ (8.24); com 6/10 vitórias, ~27% de chance de o jogo ser perdedor.

**O "capital"** = quanto você aceita perder antes de abandonar a estratégia (não o *haircut*). Pode-se usar patrimônio total com fração menor.

**Browne — maximizar P(atingir meta B no prazo T)** (equivale a hedgear uma *call* digital sobre a própria riqueza):

$$f^* = \frac{1}{\sigma\sqrt T}\;n\!\left(N^{-1}\!\left(\frac{We^{rT}}{B}\right)\right)\frac{Be^{-rT}}{W} \tag{8.33}$$

Ex.: drift 22%, σ 45%, r 8%, meta +50% em 100 pregões → f ≈ 1,8 (Kelly ≈ 0,69).

**Reversão à média (Ornstein-Uhlenbeck normalizado):** posição ótima $= -W\cdot z/2$ (8.44), $z$ = desvios da média. Cresce com o afastamento até $z = \sqrt2$, depois encolhe (perda de capital domina). Independe da velocidade de reversão. Com caudas grossas, entrar antes e sair mais rápido.

**Ponto de entrada ótimo** (desvios normais independentes): maximizar $2TS(1 - N(S))$ ⇒ $S \approx 0{,}75\sigma$ (8.46). Errar para o lado conservador.

**Paradoxo de Proebsting:** marcar a mercado antes de recalcular o Kelly.

**Perigo real:** a **média mudar** (ex.: InterOil 26/jun/2007, reprecificação fundamental). Entender por que o trade foi contra antes de aumentar.

**Regras finais:** mais edge → maior; mais variância/incerteza → menor; **stops arbitrários por preço são má ideia**; o trade deve ser grande o bastante para o lucro importar e pequeno o bastante para a perda não ser catastrófica — se não existe esse tamanho, falta edge.

---

### Cap. 9 — Trade Evaluation

**Estatísticas mínimas por ativo-objeto (nível diário):** P/L médio diário bruto e líquido; *haircut* usado; % dias vencedores/perdedores; ganho médio; perda média; maior ganho e maior perda; P/L acumulado; **máximo drawdown (magnitude e duração)**. Registrar também **trades rejeitados** e todo **override** discricionário. Repetir por ciclo de vencimento, segmentado por long/short vol e por **setor**.

**Benchmarks (definir antes):** *Success*, *Respectability*, *Failure* — cobrindo **todo** o intervalo de resultados, sem buracos. Drawdown de 10% → problemas de marketing; 30% → questões de sobrevivência (heurística).

**Sharpe:** $SR = (\mu - r)/\sigma$ (9.1). Forças: simples, intuitivo, independente de alavancagem, padrão. Fraquezas: qual taxa livre de risco; *peso problem* (vender OTM gera Sharpe de dois dígitos até a perda grande); erro amostral; qual base de capital (*haircut* usado, *haircut* permitido, dólares absolutos).

**Erro-padrão do Sharpe (Lo 2002, IID):**

$$\text{SE}(\widehat{SR}) \approx \sqrt{\frac{1 + \tfrac12SR^2}{T}}\quad(T\text{ em anos}) \tag{9.2 corrigida}$$

Com 100 dias e SR ≈ 0,66: SE ≈ 1,75 (simulação do livro: 1,61). Viés de amostra pequena ~$S/2T$ (Christie 2005).

**Alternativas** (todas históricas e mais sujeitas a amostra pequena — usar **várias**):

| Medida | Fórmula |
|---|---|
| Sortino | $(\mu - r)/\sigma_d$, $\sigma_d$ = desvio das perdas (*downside deviation*) |
| Calmar | $(\mu - r)/\text{MaxDD}$; 1 é "bom"; regra: buscar x% de retorno ⇒ aceitar x% de drawdown |
| Sterling | $(\mu - r)/(\overline{\text{MaxDD}}_{anual,\,3a} - 10\%)$ (drawdowns em módulo); variante: média dos 5 maiores DD |
| Omega | $\Omega(r) = \dfrac{\int_r^b(1-F(x))dx}{\int_a^rF(x)dx} = \dfrac{C(r)}{P(r)} = \dfrac{E[(X-r)^+]}{E[(r-X)^+]}$ (distribuição real, sem desconto) |
| K ratio (Kestner 1996, original) | regressão $\ln(\text{VAP}_t) = \alpha + \beta t$; $K = \hat\beta/\text{SE}(\hat\beta)$ (estatística t) |

O Sharpe é cego à **ordem** dos retornos (126 dias de +1% e 126 de −0,5% dão SR ≈ 5,28 em qualquer ordem); o K ratio não.

**Escalabilidade** importa mais que Sharpe; traders "jogam" com a métrica premiada → gestão de risco **independente**.

**Metas e tamanho:** fixar antes; **não mudar o tamanho por resultados recentes** (2 dias perdedores seguidos com 80% de acerto acontecem ~10×/ano).

**Persistência relativa — CPR:**

$$CPR = \frac{GG\cdot BB}{GB\cdot BG},\qquad z = \frac{\ln CPR}{\sqrt{\frac1{GG}+\frac1{BB}+\frac1{GB}+\frac1{BG}}} \tag{9.7–9.8}$$

Significativo a 5% se $z > 1{,}96$. Ex.: 12/8/11/9 → CPR 1,23, z 0,32.

**Persistência absoluta — Hurst / R/S** (série de **log-retornos**):

$$D_{t} = \sum_{k=1}^t(x_k - M_N),\quad R = \max D - \min D,\quad R/S = (aN)^h \tag{9.10–9.12}$$

Regressão $\ln(R/S) = h\ln N + \ln a$ (9.13); aproximação de Hurst ($a = 1/2$): $h = \ln(R/S)/\ln(N/2)$ (9.14) — superestima se h > 0,7, subestima se h < 0,4. h > 0,5 persistência; h < 0,5 antipersistência.

**Avaliação de nível superior:** não "trabalhar fraquezas" — explorar o que funciona. Causas de degradação: edge sumiu, capacidade de execução caiu, contrapartes mudaram. Pergunta: "Se eu começasse hoje, escolheria este produto?"

---

### Cap. 10 — Psychology

Vieses provavelmente estão por trás da maioria das fontes de edge. **Só operar efeitos cuja fonte de *mispricing* se entende.** Conhecer vieses ajuda a explorá-los nos outros, não necessariamente a evitá-los em si (*bias blind spot*) → operar com **parceiro**, registros, estatística.

| Viés | Efeito em volatilidade | Defesa |
|---|---|---|
| Self-attribution | Vendedores de puts OTM culpam o azar ao quebrar | Estatística pós-trade; não aumentar risco após sequência boa |
| Overconfidence | Calls muito OTM (AGIX); subestimar vol | Ficar no jogo; Kelly fracionado; diversificar |
| Availability | *Straddle* do Google precificando 16% vs média histórica 7,7% | Usar histórico completo |
| Short-term thinking | Preferência por *short gamma*; ignorar custos de hedge | Hedge que minimize custos |
| Loss aversion | *Getevenitis*; origem do prêmio de vol implícita | "Gosto desta posição **agora**?" |
| Conservatism | Underreaction, momentum, *post-earnings drift* | — |
| Representativeness | Aumentar tamanho após sequência de vitórias | Conhecer a distribuição de sequências |
| Confirmation | *Talking their book* | Critérios definidos antes; buscar falseamento |
| Hindsight | "Era óbvio" → operar grande | Diário; previsões falseáveis |
| Anchoring | Implícita cai perto de máx/mín de 52 semanas; sobe ao romper | Definir níveis **antes** de ver a implícita |
| Narrative fallacy | Compradores de opções muito OTM | Estatística acima de histórias |
| Prospect theory | *Sizing* subótimo | Equivale a Kelly fracionado |

**Ancoragem (Driessen-Lin-Van Hemert 2011):** aproximando da máx 52s: −0,9 ponto de vol; da mín: −0,4; rompendo máx: +1,12; rompendo mín: +1,16.

**Sequências:** com p = 0,55, ~31% de chance de ao menos uma sequência de 8 vitórias em 100 dias (exato: 1 − 0,6932). Ver `prob_no_run` (Seção 6).

**Bom trade ≠ trade vencedor:** avaliar a decisão pelo raciocínio, não pelo resultado.

**Checklist do autor:** não operar demais nem grande demais; não precisar estar absolutamente certo; long vol perde na maioria dos dias; admitir erros; parceiro; saber a fonte do edge; pesar informação nova pelo contexto e tamanho da amostra; buscar evidência contrária; avaliar cada trade pelos méritos atuais.

---

### Cap. 11 — Generating Returns through Volatility

***Alpha* vs *beta*:** vender variância de **índice** é **beta** (prêmio por risco), não habilidade. Não pagar preço de alpha por beta.

**Evidência:** Coval-Shumway (straddles de índice vendidos: 3%/semana, Sharpe 1,2); comprar calls/puts de índice não foi lucrativo, nem com 1987.

**Backtests em QQQ** (jan/2000–abr/2010; 2º vencimento; delta-hedge semanal; margem por estratégia; US$ 100 mil):

| Estratégia vendida | Ret. semanal médio (anual.) | Ret. total (anual.) | Sharpe | MaxDD |
|---|---|---|---|---|
| Strangle 10Δ | 19,9% | 41,6% | 1,32 | 20,6% |
| Strangle 20Δ | 26,7% | 93,3% | 1,21 | 34,2% |
| Strangle 30Δ | 22,5% | 64,1% | 1,14 | 32,9% |
| Straddle ATM | 21,7% | 58,6% | 1,14 | 32,7% |
| Strangle 20Δ, só VIX < 35 | 17,8% | 41,7% | 1,30 | 31,4% |
| Strangle 20Δ, só VIX < EWMA(0,95) | 21,8% | 69,8% | 1,68 | 10,3% |
| Vender risk reversal 30Δ | 13,5% | 22,2% | 0,69 | 26,9% |

*Interpretação (não definida no livro):* "retorno total (anualizado)" ≈ lucro total / capital inicial / anos, **sem capitalização**.

- Filtro de **nível** (VIX < 35): robusto; suaviza a curva, evita 2008. Base: prêmio proporcionalmente maior com implícita baixa.
- Filtro de **média móvel** (VIX < EWMA): melhores números, **menos robusto**, risco de *curve fitting* (ganho concentrado antes de 2004). EWMA: $\text{EWMA}_t = 0{,}95\,\text{EWMA}_{t-1} + 0{,}05\,\text{VIX}_t$ (forma usual; meia-vida ≈ 13,5 obs.; frequência não informada).

**Ações individuais (Dow, 2002–2010, strangles 30Δ):** Sharpe médio ≈ 0,48; drawdowns médios ≈ 54% → o prêmio é em grande parte **efeito de índice**.

**Origem:** prêmio de **correlação** (dispersion trading: vender vol de índice, comprar de componentes = *short correlation*; sofre nas crises) e prêmio de **assimetria** (puts OTM; Kozhan-Neuberger-Schneider: ~metade do excesso de retorno das puts OTM vem do *realized skewness*). Explicações: seguro, aversão a assimetria negativa/curtose, perdas correlacionadas com quedas; *calls* OTM caras por busca de "loteria". *Peso problem* não é explicação.

---

### Cap. 12 — The VIX

**Variância implícita *model-free*** (Carr-Madan; Britten-Jones-Neuberger; Jiang-Tian):

$$E[V_{0,T}] = \frac2T e^{rT}\left[\int_0^F\frac{P(T,X)}{X^2}dX + \int_F^\infty\frac{C(T,X)}{X^2}dX\right] \tag{12.2}$$

Raiz introduz viés **para cima** (Jensen): $\sqrt{E[V]} \ge E[\sqrt V]$.

**Fórmula do VIX** (por vencimento; $X_0$ = strike imediatamente **abaixo** de $F$; $V(X_i)$ = mid da OTM; em $X_0$ média de put e call):

$$\sigma^2 = \frac2T\sum_i\frac{\Delta X_i}{X_i^2}e^{rT}V(X_i) - \frac1T\left(\frac F{X_0} - 1\right)^2 \tag{12.3}$$

$$F = X_0 + e^{rT}(C_0 - P_0)\;\text{(no strike onde } |C-P| \text{ é mínimo)},\qquad \Delta X_i = \frac{X_{i+1} - X_{i-1}}2 \tag{12.4–12.5}$$

Interpolação para 30 dias constantes ($N$ em minutos):

$$VIX = 100\sqrt{\left[T_1\sigma_1^2\frac{N_{T2}-N_{30}}{N_{T2}-N_{T1}} + T_2\sigma_2^2\frac{N_{30}-N_{T1}}{N_{T2}-N_{T1}}\right]\frac{N_{365}}{N_{30}}} \tag{12.6}$$

*Cash VIX* não é negociável; futuros de VIX **não** seguem *cash and carry* (fair value depende de modelo).

**Base do VIX (Simon-Campasano 2012):** futuro acima do cash tende a cair; abaixo tende a subir (contra expectativas racionais). Base média do 1º vencimento: +0,66. Regra: se convergência diária esperada > 0,1 ponto → vender (base +) ou comprar (base −) o 1º futuro, segurar 5 dias. *Interpretação:* convergência diária = base / dias até o vencimento.

| | Shorts sem hedge | Longs sem hedge | Shorts com hedge SPX | Longs com hedge SPX |
|---|---|---|---|---|
| P/L médio | 656 | 1.040 | 539 | 908 |
| V/P | 53/29 | 22/20 | 55/27 | 27/15 |

Hedge: comprado em VIX → comprar futuro de S&P; vendido → vender; razão por regressão (retornos do índice e retornos escalados pelo prazo).

**Roll do VXX** (rola 1/30 do 1º para o 2º futuro por dia):

$$\text{custo diário} \approx \frac{F_2 - F_1}{30}\;(\text{contango} \Rightarrow \text{decaimento})$$

Ex.: 17,9 e 19,5 → 0,053 ponto/dia ≈ 0,3%/dia. VXX: correlação > 90% com VIX; VIX 1,5–2× mais volátil. VXZ: VIX 3–4× mais volátil.

**IVTS** $= VIX/VXV$ (VXV hoje se chama **VIX3M**) (12.7). IVTS > 1 = *backwardation* → futuros tendem a subir.

**Pesos Donninger (Tabela 12.3):**

| IVTS | VXX | VXZ | Soma |
|---|---|---|---|
| ≤ 0,91 | −0,60 | 0,40 | −0,20 |
| (0,91; 0,97] | −0,32 | 0,68 | +0,36 |
| (0,97; 1,05] | −0,25 | 0,75 | +0,50 |
| > 1,05 | −0,10 | 0,90 | +0,80 |

Resultado (ago/2010–ago/2012): 99% a.a., MaxDD 12%, Sharpe 2,62 (vs vender VXX: Sharpe 1,5, drawdown enorme). Apenas 2 anos e *thresholds* escolhidos → risco de *curve fitting*.

**Outros:** *calendar put spread* em contango (comprar put ATM do 1º, vender mesmo valor em dólares do 2º): 15,2% a.a., Sharpe 1,2, MaxDD 18% (2009–2011). **Prêmio de variância das opções de VIX** ≈ 3,26% (Barnea-Hogan, 2006–2010): vender straddles/strangles de VIX ou comprar *1×2 put spreads* (comprar 1 put de strike alto, vender 2 de strike baixo → short vega e short direcional).

---

### Cap. 13 — Leveraged ETFs

**Volatility drag:** $(1+x)(1-x) = 1 - x^2$. Ex.: ±5% → −0,25%; 2×: ±10% → −1%.

**Dinâmica e solução** (rebalanceamento contínuo, sem custos de financiamento, referência GBM):

$$dL = L\lambda\frac{dS}{S},\qquad L_t = L_0\left(\frac{S_t}{S_0}\right)^\lambda\exp\!\left(-\tfrac12\lambda(\lambda-1)\sigma^2t\right) \tag{13.1, 13.6}$$

σ = vol **realizada** no caminho. Fator de drag relativo: λ=2 ou −1 → $e^{-\sigma^2t}$; λ=3 ou −2 → $e^{-3\sigma^2t}$; λ=−3 → $e^{-6\sigma^2t}$. Não há alavancagem "crítica" que leve a zero; o mito é falso (ex.: UBT +82,1% vs 2×TLT = 75,8%, jun/2011–jun/2012).

**Visão Kelly:** emissor faz aposta alavancada fixa; Kelly ótimo $r/\sigma^2$, crescimento negativo acima de **2×** o Kelly.

**Long-short puro em vol realizada** (comprar US$ 1 de L, vender US$ λ de S):

$$E = \left(\frac S{S_0}\right)^\lambda e^{-\frac12\lambda(\lambda-1)\sigma^2t} - \lambda\frac S{S_0} - (1-\lambda) \tag{13.8}$$

Para λ = 2: $E = x^2e^{-\sigma^2t} - 2x + 1$; *breakevens*

$$x = e^{\sigma^2t}\left(1 \pm \sqrt{1 - e^{-\sigma^2t}}\right) \tag{13.10}$$

Payoff parece *long straddle*, mas é **short vol realizada**: ganha com tendência persistente e vol baixa. Ex.: σ=30%, t=1 → breakevens 0,773 e 1,415; parado → −8,6%. A posição inversa (vender LETF, comprar λ× referência) é long vol realizada.

**Opções sobre LETF (via Carr-Madan):**

$$g(S) = g(c) + g'(c)(S-c) + \int_0^cg''(X)(X-S)^+dX + \int_c^\infty g''(X)(S-X)^+dX \tag{13.11}$$

$L$ com λ = 2 é uma *power option* perpétua: $O = 2\frac{L_0}{S_0^2}e^{-\sigma^2t}\int_0^\infty C(X)dX$ (cesta de calls com pesos iguais).

Strike de fronteira (em unidades de $S/S_0$), **forma corrigida:**

$$k^* = \left(\frac{k}{L_0}\exp\!\left(\frac{\lambda^2-\lambda}2\sigma^2t\right)\right)^{1/\lambda}$$

Com $A = \frac{L_0}{S_0}|\lambda|\exp\!\left(\frac{\lambda-\lambda^2}2\sigma^2t\right)$ e $C_S(\cdot), P_S(\cdot)$ opções sobre a referência no mesmo vencimento:

| Caso | Fórmula (verificada numericamente) |
|---|---|
| Call, λ > 0 | $A\left[(k^*)^{\lambda-1}C_S(S_0k^*) + (\lambda-1)\int_{k^*}^\infty X^{\lambda-2}C_S(S_0X)dX\right]$ |
| Put, λ > 0 | $A\left[(k^*)^{\lambda-1}P_S(S_0k^*) - (\lambda-1)\int_0^{k^*}X^{\lambda-2}P_S(S_0X)dX\right]$ |
| Call, λ < 0 | $A\left[(k^*)^{\lambda-1}P_S(S_0k^*) + (1-\lambda)\int_0^{k^*}X^{\lambda-2}P_S(S_0X)dX\right]$ |
| Put, λ < 0 | $A\left[(k^*)^{\lambda-1}C_S(S_0k^*) - (1-\lambda)\int_{k^*}^\infty X^{\lambda-2}C_S(S_0X)dX\right]$ |

**Comparar vols:** a vol implícita do LETF deve ser ≈ $|\lambda|$ × vol implícita da referência no strike $S_0k^*$; para $k = L_0$ ("strike mais provável"):

$$S = S_0\exp\!\left(\frac{\lambda^2-\lambda}{2\lambda}\sigma^2t\right) \tag{13.20}$$

(λ=2, σ=20%, t=1 → ≈ 1,02 S₀.) Na prática (SSO, jul/2012) o mercado fica muito perto disso.

---

### Cap. 14 — Life Cycle of a Trade (fluxo operacional)

1. **Pré-trade (o mais importante):** medir vol com vários estimadores (CC, Parkinson, GK, RS, YZ, GARCH, alta frequência) + cone → previsão de consenso; comparar com implícita → *edge* relativo; comparar com o *edge* do mercado (índice/VIX) → edge **absoluto e relativo**; identificar o **catalisador** e por que o mercado erra.
2. **Execução e hedge:** tamanho adequado; hedge com banda predeterminada (Zakamouline).
3. **Durante:** rehedge segundo o plano; **reavaliar continuamente** (nova previsão, nova implícita, vega restante) no contexto da carteira.
4. **Saída:** quando o edge se realizou, a previsão mudou significativamente ou a opção venceu. **Nunca sair só por ter perdido dinheiro.**
5. **Pós-trade:** retorno sobre *haircut*, dias perdedores e causas; comparar com o lucro esperado.

Caso AAPL (jun/2007): previsão 29, implícita 41 → edge ≈ 41% (normal da AAPL 20–25%; mercado: VIX 16,5 vs previsão 12,6 → 31%). Short ~US$ 1.450–1.900 vega; saída em 7 dias com US$ 18.390 sobre *haircut* médio US$ 76.805 (23,9%). Se mantido: US$ 6.718 vs esperado 1.900 × (41,6 − 30,1) = 21.850, mesmo com previsão quase exata (30,1 realizada) — *path dependence* (dia 5/jul: −21.766). Lucro esperado aproximado: $|\text{vega}|\times(\sigma_{impl} - \sigma_{prev})$ em pontos.

Preferir trades com **catalisadores datados** que movam a implícita a favor.

---

### Cap. 15 — Conclusion (o processo)

Processo consistente: **(1) objetivo único** (explicável em uma frase) → **(2) edge** (previsão vs implícita + entender por quê) → **(3) captura** (hedge eficiente; path dependence) → **(4) sizing** coerente com o objetivo → **registros**. Além do conhecimento: execução, concentração e **escolha do produto** (provavelmente o maior fator). "Um modelo não é uma estratégia, e uma estratégia não é um negócio."

---
## 4. Regras de decisão e heurísticas

Regras que a plataforma pode transformar em alertas, validações, *checklists* ou relatórios. Cada uma cita o capítulo de origem.

### 4.1 Encontrar o trade (sinal)

| # | Regra | Cap. |
|---|---|---|
| S1 | Sinal = previsão de vol realizada **diverge significativamente** da implícita ATM, **depois de subtrair o *spread* normal** (prêmio de variância) daquele produto. | 4, 15 |
| S2 | Exigir edge relativo maior que o do **índice** no mesmo momento (o *spread* do índice é a vantagem mínima). | 4, 14 |
| S3 | Mostrar a implícita contra o **cone** de vol realizada (percentis por horizonte), não só contra uma previsão pontual. | 4 |
| S4 | Exigir uma **causa identificada** para o *mispricing* (catalisador, viés, fluxo). Sem causa entendida, não operar. | 10, 15 |
| S5 | Usar **vários estimadores**; divergências (ex.: Parkinson ≫ CC) são informação. | 2, 14 |
| S6 | Excluir eventos únicos (resultados) da previsão, a menos que o período previsto contenha outro evento; para eventos, calcular o **salto implícito** (eqs. 5.2–5.4) e comparar com o histórico completo de saltos (não só o último). | 4, 5, 10 |
| S7 | Antes de resultados: implícita do 1º vencimento sobe e despenca após; **dispersão das estimativas** dos analistas é o filtro útil. | 5 |
| S8 | Monitorar a **superfície normalizada** (vol/ATM por delta) contra seu equilíbrio histórico; desvios = oportunidade. | 5 |
| S9 | Vencimentos longos sobrerreagem a mudanças no curto (Stein): constante ~0,85 teórica vs ~0,95 de mercado. | 5 |
| S10 | Vender vol de **índice** é beta com prêmio persistente; em ações individuais o prêmio não é confiável. Filtro de nível (vol baixa) é mais robusto que filtro de média móvel. | 11 |
| S11 | VIX: base (futuro − cash) prevê a direção dos futuros; IVTS > 1 = backwardation → futuros tendem a subir. | 12 |
| S12 | O usuário deve **definir seus níveis de compra/venda antes de ver a implícita** (anti-ancoragem). | 10 |
| S13 | Preferir trades com **catalisador datado** capaz de mover a implícita a favor. | 14 |

### 4.2 Dimensionar (sizing)

| # | Regra | Cap. |
|---|---|---|
| Z1 | Fração ótima ≈ $r/\sigma^2$ do trade (retorno em excesso esperado / variância do P/L). Padrão recomendado: **Kelly fracionado** (≤ ½). Nunca acima de 1× Kelly; 2× = crescimento zero. | 8 |
| Z2 | "Capital" = quanto o usuário aceita perder antes de abandonar a estratégia (configurável). **Não** usar o *haircut*. | 8, 9 |
| Z3 | Penalizar estimativas com poucos dados: $\bar p = (w+1)/(N+2)$ e mostrar a incerteza da fração de Kelly. | 8 |
| Z4 | Para metas com prazo, oferecer Browne (eq. 8.33) — avisando que aceita probabilidade de ruína. | 8 |
| Z5 | Em reversão à média, a posição ótima **aumenta** com o afastamento até $z = \sqrt2$ e depois **diminui**; entrada ótima ≈ 0,75σ. | 8 |
| Z6 | **Não** alterar o tamanho por sequências recentes (ganhos ou perdas); mostrar ao usuário a probabilidade da sequência sob o histórico (`prob_no_run`). | 9, 10 |
| Z7 | Teste de sanidade: existe um tamanho em que o lucro importa e a perda não é catastrófica? Se não, o edge é insuficiente. | 8 |
| Z8 | Lembrar que vol "parece" igual a custo: aumentar o *bid/ask* esperado reduz o tamanho atrativo (Leland). | 6 |

### 4.3 Capturar (hedge)

| # | Regra | Cap. |
|---|---|---|
| H1 | Hedge por **banda** (Zakamouline > Whalley-Wilmott > ad hoc); ao sair da banda, ajustar **até a borda**. | 6 |
| H2 | Banda mais estreita quando **vendido** em gamma; mais larga quando comprado. | 6 |
| H3 | Estimar **antes** quanto do edge o hedge consumirá (Leland, eq. 6.7–6.8). | 6 |
| H4 | Usar **delta total** com a dinâmica de *smile* escolhida (eq. 5.8). | 5 |
| H5 | Escolher a vol de hedge pela Tabela 7.3 (tendência vs lateral; comprado vs vendido). Hedge na implícita = P/L suave; na realizada = resultado final mais certo. | 7 |
| H6 | Mostrar a dispersão esperada do P/L por hedge discreto (eq. 7.7) junto do P/L esperado. | 7 |
| H7 | Risco de salto não se hedgeia com o ativo: sugerir asas compradas, diversificação e tamanho. | 1, 6 |
| H8 | Agregar deltas por índice (eq. 6.23) é opcional; abordagem conservadora: bandas por ativo + monitor de risco agregado. | 6 |
| H9 | Gamma que muda de sinal (borboletas, *spreads*): considerar o perfil global; preferir hedge estático com opções. | 6 |

### 4.4 Gerir e sair

| # | Regra | Cap. |
|---|---|---|
| G1 | Reavaliar continuamente: nova previsão × nova implícita × vega restante. A pergunta é "eu entraria nesta posição **agora**?". | 10, 14 |
| G2 | **Sem stop por P/L.** Sair quando o edge se realizou, a previsão mudou ou o produto mudou estruturalmente. | 8, 14 |
| G3 | Antes de aumentar uma posição perdedora em vol: verificar se a **média mudou** (notícia, reprecificação fundamental, volume anômalo). | 8 |
| G4 | Reduzir risco perto de feriados/baixa diversificação do livro. | 14 |

### 4.5 Avaliar (relatórios)

| # | Regra | Cap. |
|---|---|---|
| A1 | Registrar estatísticas **diárias** por ativo (lista do Cap. 9), trades **rejeitados** e todos os **overrides**. | 9 |
| A2 | Relatório por ciclo de vencimento, segmentado por long/short vol e por **setor**. | 9 |
| A3 | Mostrar **várias** métricas (Sharpe com IC de Lo, Sortino, Calmar, Sterling, Omega, K ratio) e **drawdown** (magnitude e duração) em destaque. | 9 |
| A4 | Benchmarks *success/respectability/failure* definidos antes e cobrindo todo o intervalo. | 9 |
| A5 | Persistência: CPR (entre traders/estratégias) e Hurst (série de log-retornos de um trader). | 9 |
| A6 | Separar **processo** de **resultado** ("bom trade ≠ trade vencedor"); diário com previsões falseáveis. | 9, 10 |

---

## 5. Tabelas de referência numérica

**b(N) — viés da vol amostral (Tab. 2.1):** 5 → 0,840749; 10 → 0,922746; 20 → 0,961945; 50 → 0,984912; 100 → 0,992478; 200 → 0,996245.

**SE da vol amostral para σ = 30% (Tab. 2.2):** N=5: 0,0916; 10: 0,0661; 20: 0,0471; 30: 0,0386; 50: 0,0299; 100: 0,0212.

**Cone MSFT (4 anos até 30/04/2007, Tab. 4.1):**

| | 20d | 40d | 60d | 120d |
|---|---|---|---|---|
| Máx | 0,465 | 0,352 | 0,287 | 0,258 |
| p75 | 0,213 | 0,213 | 0,225 | 0,200 |
| Mediana | 0,159 | 0,172 | 0,169 | 0,181 |
| p25 | 0,123 | 0,149 | 0,147 | 0,161 |
| Mín | 0,062 | 0,096 | 0,091 | 0,136 |

**Prêmio de vol do S&P 500 por nível do VIX (jan/1990–mai/2012, Tab. 4.3):**

| VIX | Dias | *Spread* médio (implícita vs realizada) |
|---|---|---|
| < 20 | 3.102 | 27,75% |
| 20–30 | 1.925 | 19,78% |
| 30–40 | 407 | 13,73% |
| 40–50 | 111 | 9,26% |
| > 50 | 56 | −11,52% |

**Estrutura a termo do VIX (2006–2011):** VIX médio 23,7; futuros 1º/2º 23,8/24,4; com VIX < 20 a curva foi descendente 22% do tempo; com VIX 40–50 foi ascendente 46% do tempo.

**Fração da variância no pregão:** ações EUA ~85%; índices ~90%; ADRs ~60–70%.

**Curtose em excesso (Tab. 3.1):** WTI 2,1; DAX 4,5; ouro 5,1; FTSE 7,9; Nasdaq 9,9; IBM 9,9; Hang Seng 32,7; S&P 500 (1950–2011) 21,3.

**Persistência do VIX:** vol anualizada do VIX por frequência: 0,96 / 0,84 / 0,59 (diário/semanal/mensal); autocorrelação dos retornos: −0,04 / −0,21 / −0,12.

---
## 6. Implementação de referência (Python)

Módulo único, dependências `numpy` e `scipy`. Todas as funções seguem as formas **corrigidas** da Seção 2 e foram validadas pelos casos da Seção 7. Pode ser copiado para o projeto (ex.: `voltrading_ref.py`) ou portado para outra linguagem mantendo os mesmos testes.

```python
"""Implementações de referência — Sinclair, Volatility Trading (2ª ed.), fórmulas corrigidas.
Convenções: vols/taxas anualizadas em fração decimal; T em anos; retornos log; 252 pregões/ano."""
import math
import numpy as np
from scipy.stats import norm
from scipy.special import gammaln
from scipy.integrate import quad

ANN = 252

# ---------------- Cap. 1 — BSM ----------------
def bsm(S, K, T, r, sigma, q=0.0, kind="call"):
    """Preço e gregas BSM (q = dividend yield / custo de carregamento; futuro: q = r)."""
    sqT = math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * sqT)
    d2 = d1 - sigma * sqT
    df_r, df_q = math.exp(-r * T), math.exp(-q * T)
    if kind == "call":
        price = S * df_q * norm.cdf(d1) - K * df_r * norm.cdf(d2)
        delta = df_q * norm.cdf(d1)
        theta = (-S * df_q * norm.pdf(d1) * sigma / (2 * sqT)
                 - r * K * df_r * norm.cdf(d2) + q * S * df_q * norm.cdf(d1))
    else:
        price = K * df_r * norm.cdf(-d2) - S * df_q * norm.cdf(-d1)
        delta = -df_q * norm.cdf(-d1)
        theta = (-S * df_q * norm.pdf(d1) * sigma / (2 * sqT)
                 + r * K * df_r * norm.cdf(-d2) - q * S * df_q * norm.cdf(-d1))
    gamma = df_q * norm.pdf(d1) / (S * sigma * sqT)
    vega = S * df_q * norm.pdf(d1) * sqT          # por 1.00 de vol; /100 => por ponto
    return dict(price=price, delta=delta, gamma=gamma, vega=vega, theta=theta, d1=d1, d2=d2)

# ---------------- Cap. 2 — estimadores ----------------
def vol_close_to_close(c, zero_mean=True, ann=ANN):
    r = np.diff(np.log(c))
    if zero_mean:
        return math.sqrt(np.mean(r**2) * ann)                  # eq. 2.1b
    return math.sqrt(np.var(r, ddof=1) * ann)                  # eq. 2.3

def bias_b(N):
    """b(N) da eq. 2.6: E[s] = b(N)·σ, com s calculado com 1/N e média subtraída (eq. 2.1a)."""
    return math.sqrt(2.0 / N) * math.exp(gammaln(N / 2) - gammaln((N - 1) / 2))

def bias_b_zero_mean(N):
    """Fator equivalente para s = sqrt(Σx²/N) com MÉDIA ZERO (eq. 2.1b): E[s] = b0(N)·σ.
    Não use bias_b() com o estimador de média zero."""
    return math.sqrt(2.0 / N) * math.exp(gammaln((N + 1) / 2) - gammaln(N / 2))

def vol_mean_abs(c, ann=ANN):
    """eq. 2.11: σ ≈ sqrt(π/2)·sqrt(252)·mean|R| = 19.896·mean|R|."""
    r = np.diff(np.log(c))
    return math.sqrt(math.pi / 2) * math.sqrt(ann) * np.mean(np.abs(r))

def vol_parkinson(h, l, ann=ANN):
    x = np.log(np.asarray(h) / np.asarray(l))
    return math.sqrt(np.mean(x**2) / (4 * math.log(2)) * ann)   # eq. 2.14

def vol_garman_klass(o, h, l, c, ann=ANN):
    """Forma original de Garman-Klass (1980): termo de fechamento = ln(c_i/o_i).
    O livro imprime ln(c_i/c_{i-1}); ver errata."""
    hl = np.log(np.asarray(h) / np.asarray(l))
    co = np.log(np.asarray(c) / np.asarray(o))
    return math.sqrt(np.mean(0.5 * hl**2 - (2 * math.log(2) - 1) * co**2) * ann)

def _rs_terms(o, h, l, c):
    o, h, l, c = map(np.asarray, (o, h, l, c))
    return np.log(h / c) * np.log(h / o) + np.log(l / c) * np.log(l / o)

def vol_rogers_satchell(o, h, l, c, ann=ANN):
    return math.sqrt(np.mean(_rs_terms(o, h, l, c)) * ann)      # eq. 2.16 (o = ABERTURA)

def vol_yang_zhang(o, h, l, c, ann=ANN):
    """Yang-Zhang (2000). Arrays alinhados; usa N = len-1 períodos (precisa de c_{i-1}).
    σ_o² = var(ln o_i/c_{i-1}) (noite), σ_c² = var(ln c_i/o_i) (pregão)."""
    o, h, l, c = map(np.asarray, (o, h, l, c))
    on = np.log(o[1:] / c[:-1])
    oc = np.log(c[1:] / o[1:])
    N = len(on)
    so2 = np.var(on, ddof=1)
    sc2 = np.var(oc, ddof=1)
    srs2 = np.mean(_rs_terms(o[1:], h[1:], l[1:], c[1:]))
    k = 0.34 / (1.34 + (N + 1) / (N - 1))
    return math.sqrt((so2 + k * sc2 + (1 - k) * srs2) * ann)

def vol_first_exit(taus_years, delta, n_correct=True):
    """eq. 2.19 + correção 2.26: σ = Δ/sqrt(mean τ) / (1 + 1/(4n))."""
    tau_bar = float(np.mean(taus_years)); n = len(taus_years)
    s = delta / math.sqrt(tau_bar)
    return s / (1 + 1 / (4 * n)) if n_correct else s

# ---------------- Cap. 4 — previsão ----------------
def ewma_var(returns, lam=0.94, v0=None):
    v = returns[0]**2 if v0 is None else v0
    out = []
    for r in returns:
        v = lam * v + (1 - lam) * r**2                           # eq. 4.1
        out.append(v)
    return np.array(out)

def garch_forecast(var_t, omega, alpha, beta, horizon):
    """eq. 4.5 e 4.9: E[σ²_{t+τ}] = V + (α+β)^τ (σ²_t − V). Retorna variâncias diárias τ=1..horizon."""
    V = omega / (1 - alpha - beta)
    tau = np.arange(1, horizon + 1)
    return V + (alpha + beta)**tau * (var_t - V)

def garch_term_vol(var_t, omega, alpha, beta, horizon, ann=ANN):
    """Vol média anualizada esperada até o horizonte (média das variâncias diárias previstas)."""
    return math.sqrt(np.mean(garch_forecast(var_t, omega, alpha, beta, horizon)) * ann)

def hodges_tompkins_factor(h, T):
    """eq. 4.16: multiplicador da VARIÂNCIA medida com janelas sobrepostas."""
    n = T - h + 1
    return 1.0 / (1 - h / n + (h**2 - 1) / (3 * n**2))

def vol_cone(closes, windows=(20, 40, 60, 120, 240), ann=ANN, overlap=True):
    r = np.diff(np.log(closes)); out = {}
    for h in windows:
        if overlap:
            vols = np.array([math.sqrt(np.mean(r[i:i + h]**2) * ann) for i in range(len(r) - h + 1)])
            vols *= math.sqrt(hodges_tompkins_factor(h, len(r)))
        else:
            vols = np.array([math.sqrt(np.mean(r[i:i + h]**2) * ann) for i in range(0, len(r) - h + 1, h)])
        out[h] = dict(max=vols.max(), p75=np.percentile(vols, 75), median=np.median(vols),
                      p25=np.percentile(vols, 25), min=vols.min())
    return out

def bakshi_madan_rhs(gamma, sigma, skew, kurt):
    """eq. 4.18: (σ_rn² − σ²)/σ² ≈ −γσ·skew + (γ²/2)σ²(kurt − 3). kurt = curtose total (normal = 3)."""
    return -gamma * sigma * skew + 0.5 * gamma**2 * sigma**2 * (kurt - 3)

# ---------------- Cap. 5 — dinâmica da implícita ----------------
def forward_vol(s1, T1, s2, T2):
    return math.sqrt((s2**2 * T2 - s1**2 * T1) / (T2 - T1))    # eq. 5.2

def event_vol(s1, T1, s2, T2):
    """eq. 5.3; retorna None se s1 <= s2 (mercado não precifica salto)."""
    if s1 <= s2:
        return None
    return math.sqrt((s1**2 - s2**2) * T1 * T2 / (T2 - T1))

def event_expected_move(s1, T1, s2, T2):
    sE = event_vol(s1, T1, s2, T2)
    return None if sE is None else math.sqrt(2 / math.pi) * sE  # eq. 5.4

def total_delta(delta_bsm, vega, dsigma_dS):
    return delta_bsm + vega * dsigma_dS                         # eq. 5.8

def corrado_su_call(S, K, T, r, sigma, skew, kurt):
    """eq. 5.14–5.18. kurt = curtose TOTAL (normal = 3); entra como (kurt−3)."""
    sqT = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqT)
    d2 = d1 - sigma * sqT
    C = S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    Q3 = S * sigma * sqT / 6 * ((2 * sigma * sqT - d1) * norm.pdf(d1) + sigma**2 * T * norm.cdf(d1))
    Q4 = S * sigma * sqT / 24 * ((d1**2 - 1 - 3 * sigma * sqT * d2) * norm.pdf(d1)
                                 + sigma**3 * T**1.5 * norm.cdf(d1))
    return C + skew * Q3 + (kurt - 3) * Q4

def corrado_su_put(S, K, T, r, sigma, skew, kurt):
    return corrado_su_call(S, K, T, r, sigma, skew, kurt) - S + K * math.exp(-r * T)  # eq. 5.21

def sample_skew_kurt(x):
    x = np.asarray(x); m = x.mean(); s = x.std()
    return np.mean((x - m)**3) / s**3, np.mean((x - m)**4) / s**4   # 5.10, 5.12 (kurt total)

# ---------------- Cap. 6 — hedging ----------------
def leland_vol(sigma, half_spread, dt, long=True):
    """eq. 6.7/6.8. half_spread = custo proporcional por operação (meio spread); dt em anos."""
    adj = (half_spread / sigma) * math.sqrt(8 / (math.pi * dt))
    return sigma * math.sqrt(1 - adj) if long else sigma * math.sqrt(1 + adj)

def certainty_equivalent_gamma(mu, sd, W0):
    return 2 * (mu - W0) / sd**2                                # eq. 6.6

def ww_halfwidth(S, gamma_opt, T_rem, r, lam, risk_aversion):
    """Whalley-Wilmott eq. 6.9: meia-largura da banda em torno do delta BSM."""
    return (1.5 * math.exp(-r * T_rem) * lam * S * gamma_opt**2 / risk_aversion)**(1 / 3)

def zakamouline_band(S, K, T_rem, r, sigma, lam, risk_aversion, kind="call", position=1):
    """eqs. 6.11–6.15. position = +1 comprado, −1 vendido (escala gamma/delta da carteira).
    Retorna (centro, meia_largura) em delta POR OPÇÃO multiplicado por position."""
    g = bsm(S, K, T_rem, r, sigma, kind=kind)
    Gam = abs(g["gamma"] * position)
    common = (math.exp(-r * T_rem) / sigma)**0.25
    Kz = -4.76 * lam**0.78 / T_rem**0.02 * common * (risk_aversion * S**2 * Gam)**0.15
    H0 = lam / (risk_aversion * S * sigma**2 * T_rem)
    H1 = 1.12 * lam**0.31 * T_rem**0.05 * common * (Gam / risk_aversion)**0.5
    sigma_m = sigma * math.sqrt(1 - Kz)
    center = bsm(S, K, T_rem, r, sigma_m, kind=kind)["delta"] * position
    return center, H0 + H1

def rehedge(current_delta, center, half_width):
    """Regra de banda (HN/WW/Zakamouline): fora da banda, ajusta só até a BORDA."""
    lo, hi = center - half_width, center + half_width
    if current_delta > hi:
        return hi - current_delta
    if current_delta < lo:
        return lo - current_delta
    return 0.0

def gatheral_alpha(sigma_per_unit_time, volume_per_unit_time):
    return sigma_per_unit_time / math.sqrt(volume_per_unit_time)  # eq. 6.22

def index_equivalents(beta, S_A, S_I, delta_A, gamma_A, vega_A):
    ratio = beta * S_A / S_I
    return dict(delta=ratio * delta_A, gamma=ratio**2 * gamma_A, vega=beta * vega_A)  # 6.23, 6.26, 6.27

# ---------------- Cap. 7 — distribuição do P/L hedgeado ----------------
def pl_std_discrete_hedge(vega_per_point, sigma_points, N):
    return math.sqrt(math.pi / 4) * vega_per_point * sigma_points / math.sqrt(N)  # eq. 7.7

def straddle_unhedged_pl_std(S, T, sigma):
    return S * math.sqrt(T) * sigma / math.sqrt(2)              # eq. 7.10

def atm_approx_price(S, T, sigma):
    return S * sigma * math.sqrt(T) / math.sqrt(2 * math.pi)    # eq. 7.8

# ---------------- Cap. 8 — money management ----------------
def kelly_binary(p, w, l):
    return (p * w - (1 - p) * l) / (w * l)                      # eq. 8.5

def kelly_continuous(excess_return, variance):
    return excess_return / variance                             # eq. 8.14

def growth_rate(frac_of_kelly, r, sigma):
    f = frac_of_kelly
    return (f - f**2 / 2) * r**2 / sigma**2                     # eq. 8.15

def prob_B_before_A(frac_of_kelly, A=0.5, B=2.0):
    e = 1 - 2 / frac_of_kelly
    return (1 - A**e) / (B**e - A**e)                           # eq. 8.17

def bayes_win_prob(wins, n):
    return (wins + 1) / (n + 2)                                 # eq. 8.24

def browne_fraction(W, B, sigma, T, r):
    """eq. 8.33: fração da riqueza no ativo de risco para maximizar P(W_T >= B)."""
    z = norm.ppf(W * math.exp(r * T) / B)
    return norm.pdf(z) * (B * math.exp(-r * T) / W) / (sigma * math.sqrt(T))

def ou_position(W, zscore):
    return -W * zscore / 2                                      # eq. 8.44

# ---------------- Cap. 9 — avaliação ----------------
def sharpe(returns, rf_per_period=0.0, ann=ANN):
    ex = np.asarray(returns) - rf_per_period
    return ex.mean() / ex.std(ddof=1) * math.sqrt(ann)          # eq. 9.1

def sharpe_se_lo(sr_annual, T_years):
    """Lo (2002), IID: Var(SR̂) ≈ (1 + SR²/2)/T ⇒ SE = sqrt((1+SR²/2)/T). (Eq. 9.2 do livro tem erro.)"""
    return math.sqrt((1 + 0.5 * sr_annual**2) / T_years)

def sortino(returns, target=0.0, ann=ANN):
    ex = np.asarray(returns) - target
    dd = math.sqrt(np.mean(np.minimum(ex, 0)**2))
    return ex.mean() / dd * math.sqrt(ann)                      # eq. 9.3 (σ_d = downside deviation)

def max_drawdown(equity):
    eq = np.asarray(equity, float); peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / peak
    i = int(np.argmin(dd)); j = int(np.argmax(eq[:i + 1])) if i > 0 else 0
    return -dd[i], j, i                                         # magnitude, índice pico, índice vale

def calmar(annual_excess_return, maxdd):
    return annual_excess_return / maxdd                         # eq. 9.4

def sterling(annual_excess_return, annual_maxdds_last3y):
    return annual_excess_return / (np.mean(np.abs(annual_maxdds_last3y)) - 0.10)

def omega(returns, threshold=0.0):
    x = np.asarray(returns) - threshold
    return np.sum(np.maximum(x, 0)) / np.sum(np.maximum(-x, 0))  # eq. 9.5 ≡ 9.6 (empírico)

def k_ratio(equity):
    y = np.log(np.asarray(equity, float)); t = np.arange(len(y))
    X = np.vstack([np.ones_like(t), t]).T
    coef, res, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coef
    s2 = resid @ resid / (len(y) - 2)
    se_b = math.sqrt(s2 / np.sum((t - t.mean())**2))
    return coef[1] / se_b                                       # inclinação / SE (estatística t)

def cpr_test(GG, GB, BG, BB):
    cpr = GG * BB / (GB * BG)
    z = math.log(cpr) / math.sqrt(1 / GG + 1 / BB + 1 / GB + 1 / BG)
    return cpr, z                                               # eqs. 9.7, 9.8

def rescaled_range(x):
    x = np.asarray(x); D = np.cumsum(x - x.mean())
    return (D.max() - D.min()) / x.std()                        # 9.10–9.11 / S

def hurst_approx(x):
    return math.log(rescaled_range(x)) / math.log(len(x) / 2)   # eq. 9.14

def hurst_regression(x, sizes=None):
    x = np.asarray(x); N = len(x)
    sizes = sizes or [int(s) for s in np.unique(np.logspace(math.log10(8), math.log10(N // 2), 10).astype(int))]
    pts = []
    for n in sizes:
        rs = [rescaled_range(x[i:i + n]) for i in range(0, N - n + 1, n)]
        pts.append((math.log(n), math.log(np.mean(rs))))
    a = np.array(pts)
    return np.polyfit(a[:, 0], a[:, 1], 1)[0]                   # eq. 9.13

# ---------------- Cap. 10 — sequências ----------------
def prob_no_run(N, p, j):
    """Prob. exata de NÃO haver sequência de j sucessos em N tentativas (recursão)."""
    state = np.zeros(j); state[0] = 1.0
    for _ in range(N):
        new = np.zeros(j)
        new[0] = state.sum() * (1 - p)
        new[1:] = state[:-1] * p
        state = new
    return state.sum()

def prob_no_run_feller(N, p, j, iters=50):
    """Aproximação 10.1 com x corrigido (raiz de 1 − x + q p^j x^{j+1} = 0 perto de 1)."""
    q = 1 - p; x = 1.0
    for _ in range(iters):
        x = 1 + q * p**j * x**(j + 1)
    return (1 - p * x) / ((j + 1 - j * x) * q) / x**(N + 1)

# ---------------- Cap. 12 — VIX ----------------
def vix_term_variance(strikes, call_mid, put_mid, T, r):
    """eqs. 12.3–12.5 para UM vencimento (metodologia CBOE simplificada:
    sem regra de corte por bids zerados). Retorna σ² anualizada."""
    K = np.asarray(strikes, float); C = np.asarray(call_mid, float); P = np.asarray(put_mid, float)
    i = int(np.argmin(np.abs(C - P)))
    F = K[i] + math.exp(r * T) * (C[i] - P[i])                  # eq. 12.4
    K0 = K[K <= F].max()
    Q = np.where(K < K0, P, np.where(K > K0, C, 0.5 * (C + P)))
    dK = np.empty_like(K)
    dK[1:-1] = (K[2:] - K[:-2]) / 2                             # eq. 12.5 CORRIGIDA (diferença)
    dK[0] = K[1] - K[0]; dK[-1] = K[-1] - K[-2]
    return (2 / T) * np.sum(dK / K**2 * math.exp(r * T) * Q) - (1 / T) * (F / K0 - 1)**2

def vix_interpolate(T1, var1, T2, var2, N_T1, N_T2, N30=30 * 1440, N365=365 * 1440):
    w1 = (N_T2 - N30) / (N_T2 - N_T1); w2 = (N30 - N_T1) / (N_T2 - N_T1)
    return 100 * math.sqrt((T1 * var1 * w1 + T2 * var2 * w2) * N365 / N30)  # eq. 12.6

def vxx_daily_roll(F1, F2, days=30):
    return (F2 - F1) / days                                     # correção da conta do livro

def ivts_weights(vix, vix3m):
    ivts = vix / vix3m                                          # eq. 12.7
    if ivts <= 0.91: return ivts, -0.60, 0.40
    if ivts <= 0.97: return ivts, -0.32, 0.68
    if ivts <= 1.05: return ivts, -0.25, 0.75
    return ivts, -0.10, 0.90                                    # Tabela 12.3

# ---------------- Cap. 13 — ETFs alavancados ----------------
def letf_value(L0, S_over_S0, lam, sigma_real, t):
    return L0 * S_over_S0**lam * math.exp(-0.5 * lam * (lam - 1) * sigma_real**2 * t)  # eq. 13.6

def letf_longshort_equity(x, lam, sigma_real, t):
    return x**lam * math.exp(-0.5 * lam * (lam - 1) * sigma_real**2 * t) - lam * x - (1 - lam)  # 13.8

def letf_breakevens_lambda2(sigma_real, t):
    a = math.exp(-sigma_real**2 * t)
    return (1 - math.sqrt(1 - a)) / a, (1 + math.sqrt(1 - a)) / a  # eq. 13.10

def letf_kstar(k, L0, lam, sigma, t):
    """Strike de fronteira em unidades de S/S0 (sinal CORRIGIDO vs. eq. 13.16 do livro)."""
    return (k / L0 * math.exp((lam**2 - lam) / 2 * sigma**2 * t))**(1 / lam)

def letf_option(k, L0, S0, lam, sigma, t, call_S, put_S, kind="call"):
    """Opção europeia sobre o ETF alavancado via Carr-Madan, usando funções de preço
    call_S(K), put_S(K) de opções sobre a referência (mesmo vencimento t).
    Fórmulas 13.15/13.17 (como no livro) e 13.18/13.19 CORRIGIDAS."""
    E = math.exp((lam - lam**2) / 2 * sigma**2 * t)
    ks = letf_kstar(k, L0, lam, sigma, t)
    pre = L0 / S0 * abs(lam) * E
    f = lambda X, fn: X**(lam - 2) * fn(S0 * X)
    if lam > 0 and kind == "call":
        return pre * (ks**(lam - 1) * call_S(S0 * ks) + (lam - 1) * quad(f, ks, np.inf, args=(call_S,), limit=200)[0])
    if lam > 0 and kind == "put":
        return pre * (ks**(lam - 1) * put_S(S0 * ks) - (lam - 1) * quad(f, 0, ks, args=(put_S,), limit=200)[0])
    if lam < 0 and kind == "call":
        return pre * (ks**(lam - 1) * put_S(S0 * ks) + (1 - lam) * quad(f, 0, ks, args=(put_S,), limit=200)[0])
    if lam < 0 and kind == "put":
        return pre * (ks**(lam - 1) * call_S(S0 * ks) - (1 - lam) * quad(f, ks, np.inf, args=(call_S,), limit=200)[0])
    raise ValueError

# ---------------- Cap. 14 — edge ----------------
def relative_edge(implied, forecast):
    return (implied - forecast) / forecast
```

---

## 7. Casos de teste

Valores conferidos com o código da Seção 6 (tolerâncias sugeridas entre parênteses). Use-os como testes unitários.

| Função | Entrada | Esperado |
|---|---|---|
| `bias_b` | N = 5; N = 100 | 0,840749; 0,992478 (1e-5) |
| `bias_b_zero_mean` | N = 5; N = 20; N = 100 | 0,951533; 0,987583; 0,997503 (1e-5) |
| `hodges_tompkins_factor` | h = 60, T = 1006 | ≈ 1,066 (0,01) |
| GARCH vol LP | ω = 5,05e-6, α = 0,053, β = 0,884 | ≈ 0,142 anual (0,005) |
| `bakshi_madan_rhs` | resolver γ: σ=0,136, skew −0,1, kurt 3,6, implícita 0,156 | γ ≈ 6,4; EEM (0,186, −0,05, 3,5) → implícita ≈ 0,221 |
| `event_expected_move` | 45%/10d, 35%/38d (dias/365) | ≈ 0,0435 |
| `corrado_su_call` | S=50, K=55, T=50/365, r=5%, σ=50%, skew −0,7, kurt 4 | = integral numérica da densidade de Gram-Charlier (1,5846) |
| `corrado_su_call` | S=50, K=65, T=50/365, r=5%, σ=50%, skew −0,7, **kurt total 0** | ≈ −0,212 (exemplo de preço negativo do livro) |
| `leland_vol` | σ=10%, meio *spread* 0,5%, Δt = 1/365, vendido | ≈ 0,159 |
| `certainty_equivalent_gamma` | μ=10.000, σ=2.000, EC=8.000 | 0,001 |
| `index_equivalents` | β=1,5, S_A=100, S_I=1000, Δ_A=1000 | Δ_I = 150 |
| `pl_std_discrete_hedge` | vega 1.000/ponto, σ = 30 pontos, N = 252 | ≈ 1.675 (simulação do livro: 2.615; mesma ordem) |
| `kelly_binary` | p=0,55, w=l=1; p=0,45, w=2, l=1 | 0,10; 0,175 |
| `prob_B_before_A` | f = 1; f = 0,4 | 0,667; 0,941 |
| `browne_fraction` | W=1, B=1,5, σ=0,45, T=100/252, r=0,08 | ≈ 1,81 |
| `ou_position` | W=100, z=1,8 | −90 |
| entrada ótima | argmax $S(1-N(S))$ | ≈ 0,75 |
| `sharpe_se_lo` | SR=0,66, T=100/252 | ≈ 1,75 |
| `cpr_test` | GG=12, GB=8, BG=11, BB=9 | CPR 1,227; z 0,32 |
| Sharpe de ordem | 126 × (+1%) e 126 × (−0,5%) | ≈ 5,28–5,29 (qualquer permutação) |
| `prob_no_run` | N=100, p=0,55, j=8 | 0,6932 (P(≥1 sequência) ≈ 31%) |
| `vxx_daily_roll` | 17,9; 19,5 | ≈ 0,0533 |
| `vix_term_variance` | opções BSM com vol plana 20%, strikes 40–259 passo 1, T=30/365 | √σ² ≈ 0,20 (0,002) |
| `letf_breakevens_lambda2` | σ=0,30, t=1 | 0,773; 1,415 |
| `letf_option` | S0=100, L0=50, σ=25%, t=0,5, r=0, k=52; λ ∈ {2,3,−1,−2}; call e put | igual à integração direta sob log-normal (2e-3). λ=2: call 6,1997, put 8,1997 |
| Tabela 14 | 18.390 / 76.805 | 23,9% |
| Calmar | 18% / 12% | 1,5 |
| Hurst aprox. | N=64, R/S=8 | ln 8 / ln 32 ≈ 0,60 |
| Drag 3× | σ=25%, t=1 | $e^{-0{,}1875}$ ≈ 0,829 (−2× idem) |

---

## 8. Limitações e dados datados

- **Ano-base 2013.** Produtos e metodologias mudaram: VXV foi renomeado **VIX3M**; os ETNs iPath originais (VXX/VXZ) foram substituídos/reestruturados desde então; a CBOE passou a incluir vencimentos semanais do SPX no VIX. Para cálculos oficiais, usar o *white paper* atual da CBOE. Confirmar produtos e *tickers* vigentes antes de implementar.
- **Backtests do livro** (Caps. 5, 11, 12) usam custos de hoje (2013) sobre dados antigos, períodos curtos e *thresholds* escolhidos — ilustram ideias, não garantem resultados. Aplicar as ressalvas de *curve fitting* do próprio autor.
- **Fórmulas aproximadas:** Leland, Whalley-Wilmott e Zakamouline (ajuste numérico), Kamal-Derman (ordem de grandeza), Kelly contínuo (edge pequeno), aproximação de Hurst, regra do 20. Tratar como estimativas.
- **Corrado-Su** pode gerar preços negativos e violar arbitragem fora de uma região pequena de (skew, kurt); validar e restringir parâmetros.
- **LETF (Cap. 13):** fórmulas ignoram custos de financiamento, taxas do fundo e erro de rastreamento; σ é a vol realizada futura (desconhecida na precificação).
- **Adaptação a outros mercados (ex.: B3):** 252 dias úteis também é a convenção brasileira; ajustar horário de pregão (períodos intradiários), feriados, liquidação, custos (emolumentos, corretagem), regras de aluguel/venda a descoberto e o "índice de vol" de referência equivalente ao VIX. As frações de variância no pregão (85%/90%/60–70%) e os níveis do VIX são dados **dos EUA**: recalibrar localmente.
- **Não é recomendação de investimento.** As regras da Seção 4 são heurísticas do autor; a plataforma deve apresentá-las como apoio à decisão.

---

## 9. Glossário

| Termo (EN) | Significado |
|---|---|
| ATM / OTM / ITM | No / fora / dentro do dinheiro |
| Backwardation / contango | Curva de futuros descendente / ascendente |
| Base (VIX basis) | Futuro de VIX − cash VIX |
| Bias blind spot | Ver vieses nos outros e não em si |
| Breakeven volatility skew | Implícita que zera o P/L de cada strike dado um caminho (Dupire) |
| Cash VIX | O índice VIX (não negociável) |
| Close-to-close (CC) | Vol a partir de fechamentos |
| CPR (cross product ratio) | Teste de persistência relativa |
| Delta band / no-trade region | Faixa em torno do delta em que não se rehedgeia |
| Dispersion trading | Vender vol de índice e comprar dos componentes (short correlação) |
| Drawdown | Queda do pico ao vale da curva de capital |
| Edge | Vantagem estatística; aqui, (implícita − previsão)/previsão |
| EWMA | Média móvel com pesos exponenciais |
| First exit time | Tempo até o preço sair de um corredor fixo |
| GARCH | Modelo de variância condicional com reversão à média |
| Haircut | Margem/colateral exigido pela *clearing* |
| IVTS | VIX / VIX3M (estrutura a termo *model-free*) |
| Kelly (fractional) | Fração do capital que maximiza crescimento log (fração dela) |
| Leverage effect | Vol sobe quando o preço cai |
| Model-free implied variance | Variância implícita a partir de toda a cadeia de opções |
| Path dependence | P/L depende do caminho, não só do destino |
| Peso problem | Amostra sem os eventos raros que determinam o risco |
| Power option | Opção com payoff $S^\lambda$ |
| R/S, Hurst | *Rescaled range*; expoente de persistência |
| Risk reversal | Vender put OTM e comprar call OTM (ou o inverso) |
| Roll (VXX) | Custo/ganho de rolar futuros num índice de prazo constante |
| Semi-static hedging | Hedge de saltos com outras opções |
| Smile / skew | Variação da implícita por strike |
| Sticky strike / sticky delta | Regras de como o smile se move com o ativo |
| Straddle / strangle | Call + put mesmo strike / strikes diferentes OTM |
| Stylized facts | Regularidades estatísticas comuns às séries financeiras |
| Variance premium | Implícita sistematicamente acima da realizada |
| Vega | Sensibilidade do preço à vol (no livro, por ponto) |
| Volatility cone | Faixa histórica de vol realizada por horizonte |
| Volatility drag | Perda de composição: $(1+x)(1-x) = 1-x^2$ |
