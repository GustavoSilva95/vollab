# STATUS

**Atualizado em:** 2026-11-22
**Etapa atual:** Etapa 1 — Fundação (liberada, não iniciada)
**Próxima etapa:** Etapa 2 — Dados (bloqueada até o fechamento da Etapa 1)

## Aprovações

| Documento | Versão | Situação | Data |
|-----------|--------|----------|------|
| BRD | 1.0 | Aprovado | 2026-11-21 |
| PRD | 1.0 | Aprovado | 2026-11-21 |
| Relatório da Etapa 0 ([docs/pesquisa/etapa-0.md](docs/pesquisa/etapa-0.md)) e alterações A-01..A-10 | 1.0 | Aprovado | 2026-11-22 |
| BRD | 1.1 | Aprovado (incorpora A-01..A-10) | 2026-11-22 |
| PRD | 1.1 | Aprovado (incorpora A-01..A-10 e universo inicial) | 2026-11-22 |

## Feito

- Landing page com a superfície de volatilidade 3D (antes do BRD).
- BRD 1.0 escrito e aprovado.
- Entrevista de arquitetura concluída. As decisões estão no PRD §3 (ADR-01 a ADR-16).
- PRD 1.0 escrito e aprovado.
- Ambiente do projeto criado: `AGENTS.md` (contexto e regras), `CLAUDE.md`, papéis em `.claude/agents/`, `PLANO.md` e este arquivo.
- BRD e PRD atualizados para 1.1 com os resultados da Etapa 0; PLANO ajustado (fixtures na Etapa 1, COTAHIST na Etapa 2).
- **Etapa 0 concluída (2026-11-22):** relatório em `docs/pesquisa/etapa-0.md`; fixtures reais (8,5 MB, com SHA-256) em `docs/pesquisa/fixtures/`; scripts exploratórios em `docs/pesquisa/scripts/`.

## Decisões registradas

| Data | Decisão | Onde |
|------|---------|------|
| 2026-11-21 | Stack: TS (web) + Python/FastAPI (engine) + Postgres/Docker; só o engine acessa o banco | PRD §3 |
| 2026-11-21 | Coleta sob demanda com recuperação de pregões pendentes, sem agendador | ADR-07 |
| 2026-11-21 | `/entrar` leva ao cockpit; `/cadastro` mostra "em breve"; modelo de dados com `user_id` | ADR-13 |
| 2026-11-21 | Testes de referência obrigatórios no lugar de cobertura percentual; CI falha com drift do contrato | PRD §10 |
| 2026-11-22 | PM-02 validada: o endpoint aceita tickers de opção | etapa-0 §2 |
| 2026-11-22 | QA-13: regra R4 (sessão 1, `DataNegocio = DataReferencia`, remove IDs cancelados, ordena por ID) | BRD RN-DAD-01 |
| 2026-11-22 | QA-01: COTAHIST como cadastro; ativo-objeto pelo ISIN; série = (código, vencimento); estilo inferido | BRD RN-DAD-02 |
| 2026-11-22 | Estilo de exercício pelo sufixo `E` **confirmado** contra o Cadastro de Instrumentos oficial (14.003/14.003; universo inicial 2.307/2.307 em estilo, ativo, tipo, strike e vencimento) | etapa-0 §4 |
| 2026-11-22 | COTAHIST como segunda fonte B3 (OHLC oficial, cadastro, pré-filtro da coleta) | BRD §8, PRD §6 |
| 2026-11-22 | QA-02: feriados pela página da B3 + lista nacional 2001–2078 fornecida pelo usuário, complementada por 20/11, 24/12 e 31/12 (conferida 100% com 2025–2026) | BRD §8, PRD §6.1 |
| 2026-11-22 | QA-04: IV de referência = mediana das IVs sincronizadas na última hora (mín. 3) | BRD RN-VOL-06 |
| 2026-11-22 | QA-05: janela de sincronização de 10 s | BRD RN-VOL-03 |
| 2026-11-22 | QA-06: padrão ≥ 10 negócios, K/S 0,9–1,1, 2 vencimentos mensais, semanais desligadas | BRD §15 |
| 2026-11-22 | RS-02: Yahoo só para histórico, conferido pelo ajuste de strike; proventos futuros manuais | BRD §8 |
| 2026-11-22 | **Universo inicial: BOVA11, BBAS3, PETR4** (configuração; BRD permite até 10). Carga inicial ≈ 18,9 mil req (~5,3 h); diária ≈ 300 req (~5 min) | PRD-NF-04 |

## Bloqueios e riscos ativos

- Calendário 2027 provisório até a B3 publicar.
- `rapinegocios` atrás do Cloudflare: monitorar bloqueios na carga inicial (1 req/s).
- Semântica de `TipoSessaoPregao = 6` e valores do Yahoo (bruto × líquido) a investigar na Etapa 2.

## Próximos passos

1. Iniciar a Etapa 1 (Fundação) com o papel de desenvolvedor, conforme o PLANO.
2. Primeiro item: monorepo e migração da landing para TypeScript; mover as fixtures para `services/engine/tests/fixtures/`.
