# JULIUS — Diagnóstico e Arquitetura

Documento vivo. Registra as decisões técnicas e o porquê de cada uma.

---

## 1. Diagnóstico do ambiente (03/10/2026)

| Item | Situação | Impacto |
|---|---|---|
| Código existente | Nenhum (pasta vazia) | Projeto nasce do zero; nada a preservar |
| Python | 3.12.10 + pip | Base do backend |
| Node.js / npm | **Não instalado** → instalado v24 LTS (portátil, sem admin, checksum verificado) | Frontend React/Vite |
| Git | 2.55 | Repositório iniciado localmente |
| PostgreSQL / Docker | Não instalados | Desenvolvimento em SQLite; Postgres em produção (Neon, gratuito). ⚠️ Migrations e Dockerfile **ainda não foram executados contra Postgres/Docker reais** nesta máquina |
| SO | Windows 11, 7,8 GB RAM | Evitar ferramentas pesadas (Docker Desktop, emuladores Android) |
| Local da pasta | Estava no **OneDrive** | O `pip` dentro do OneDrive travou (erro de acesso à memória no SSL). **Resolvido:** projeto movido para `C:\dev\julius`; venv em `%USERPROFILE%\.venvs\julius` |
| Porta 8000 | Ocupada por outro projeto do usuário | JULIUS usa a porta **8010** |

Restrição de negócio: **custo zero**. Toda escolha abaixo é gratuita (software livre ou plano gratuito).

---

## 2. Stack escolhida

| Camada | Tecnologia | Por quê |
|---|---|---|
| Backend | **Python 3.12 + FastAPI** | Já instalado; tipagem com Pydantic; ótimo ecossistema para IA/OCR; `Decimal` nativo; testes simples com pytest |
| ORM / migrations | **SQLAlchemy 2 + Alembic** | Mesmo código roda em SQLite e PostgreSQL; migrations versionadas com rollback (`downgrade`) |
| Banco local | **SQLite** (modo WAL) | Zero instalação; ideal para uso pessoal rodando no próprio PC |
| Banco produção | **PostgreSQL** (Neon, plano gratuito) | Robusto, concorrência real, backups |
| Frontend | **React + TypeScript + Vite** | Tipado, rápido, enorme comunidade, gera PWA facilmente |
| PWA / offline | **vite-plugin-pwa (Workbox) + IndexedDB (Dexie)** | Instalável no celular sem loja, funciona offline |
| Dados no cliente | **TanStack Query** | Cache, reprocessamento e estados de loading/erro padronizados |
| Gráficos | **Recharts** | Leve, declarativo, acessível o suficiente para o MVP |
| IA | Camada própria de provedores: **Gemini** (padrão, plano gratuito, multimodal), **OpenAI-compatível** (OpenAI, Groq, OpenRouter, Ollama local) e **nenhum** | Sem dependência de um único fornecedor |
| Senhas | **Argon2id** (`argon2-cffi`) | Algoritmo recomendado pela OWASP |
| Testes | pytest (backend), Vitest (frontend), Playwright (E2E) | Gratuitos e padrão de mercado |
| Deploy | 1 serviço (FastAPI servindo a API **e** o frontend compilado) no Render/Koyeb gratuito + Neon | Mesma origem → cookies seguros sem CORS |

### Por que não …
- **Tudo em Node/TypeScript no backend?** Seria viável, mas o Python já está instalado e é superior para OCR/IA e cálculos financeiros com `Decimal`.
- **React Native / Flutter agora?** Publicar em lojas custa dinheiro (Google Play US$ 25, Apple US$ 99/ano) e duplicaria a interface. O PWA roda no Android e no iOS de graça. Se um dia for necessário ir para as lojas, o **Capacitor** empacota o mesmo frontend sem reescrever.
- **Tauri/Electron para desktop?** O PWA instalado no Windows já se comporta como app de desktop.
- **SQLite também no celular (sql.js/wa-sqlite)?** Complexidade alta para pouco ganho; o celular precisa só de uma fila de lançamentos pendentes + cache de leitura, que o IndexedDB resolve bem.

---

## 3. Arquitetura

```
┌───────────────────────────── Navegador / PWA instalada ─────────────────────────────┐
│ React (telas) ─ TanStack Query (cache) ─ Dexie/IndexedDB (fila offline + cache)     │
│ Service Worker (Workbox): app shell offline                                          │
└───────────────▲─────────────────────────────────────────────────────────────────────┘
                │ HTTPS · cookie de sessão httpOnly · cabeçalho CSRF
┌───────────────┴──────────────────────── FastAPI ────────────────────────────────────┐
│ api/ (rotas finas, validação Pydantic)                                               │
│ services/ ← TODA regra de negócio e TODO cálculo financeiro (saldo, parcelas, fatura) │
│ ai/ (provedores intercambiáveis) — só interpreta texto/imagem e redige respostas     │
│ security/ (Argon2, sessões, CSRF, rate limit)    audit (histórico de alterações)     │
└───────────────▲─────────────────────────────────────────────────────────────────────┘
                │ SQLAlchemy
        SQLite (local)  |  PostgreSQL (produção)
```

**Regra absoluta:** a IA nunca soma, nunca calcula saldo, parcela ou fatura. Ela (a) transforma texto em uma *proposta* estruturada que o usuário confirma, ou (b) recebe números já calculados pelo backend e os explica.

---

## 4. Modelo de banco (inicial)

Dinheiro é sempre **inteiro em centavos** (`BIGINT`), nunca `float`. IDs são UUID gerados também no cliente (necessário para criação offline idempotente).

| Tabela | Finalidade |
|---|---|
| `users` | Conta de acesso; `settings` (JSON) guarda preferências (modo básico/avançado etc.) |
| `sessions` | Sessões de login; guarda só o **hash** do token |
| `accounts` | Contas **e** cartões (`kind = credit_card` + limite, fechamento, vencimento). Uma tabela só porque pagar fatura é uma transferência entre duas contas |
| `categories` | Categorias e subcategorias (`parent_id`), por usuário, editáveis |
| `transactions` | Toda movimentação: receita, despesa, transferência. `status` = realizada/prevista; `is_fixed`; vínculo opcional com recorrência e parcelamento; `notes` |
| `recurrences` | Regras recorrentes (aluguel todo dia 10, salário todo dia 5) |
| `installment_plans` | Compra parcelada: guarda o total e gera N transações (parcelas) |
| `budgets` | Limite mensal por categoria |
| `goals` | Metas financeiras |
| `categorization_rules` | O que o usuário corrigiu → melhora as próximas sugestões |
| `audit_logs` | Histórico: quem, o quê, quando, antes/depois |
| `ai_conversations` / `ai_messages` | Conversas com o assistente |
| `attachments` | Comprovantes e notas (fase OCR) |

Decisões deliberadas (evitar tabela sem finalidade):
- **Saldos não são armazenados** — são calculados a partir das transações. Saldo gravado em coluna fica dessincronizado; o cálculo por SQL é rápido para o volume de uma pessoa. Se crescer, adiciona-se snapshot mensal sem mudar a API.
- **Receitas e despesas** não são tabelas separadas: são `transactions.type`. Separar duplicaria lógica e quebraria relatórios.
- **Formas de pagamento** são um conjunto fixo (pix, débito, crédito, dinheiro, boleto, transferência, outro) validado por constraint — não precisam de tabela.
- **Notas** = coluna `notes` na transação.

### Regras contábeis
- Receita aumenta o saldo da conta; despesa reduz; **transferência** move valor entre contas e **não entra** como receita nem despesa nos relatórios.
- Compra no cartão = despesa na data da compra (regime de competência), aumenta a dívida do cartão. Pagar a fatura = transferência conta → cartão (não é despesa de novo, evitando contar duas vezes).
- Parcelamento R$ 1.200 em 12× = 12 transações de R$ 100, cada uma com sua data/fatura. Centavos que sobram na divisão vão para a 1ª parcela (R$ 100,00 em 3× → 33,34 + 33,33 + 33,33).
- Recorrências geram **previsões virtuais**. Quando a ocorrência é efetivada, cria-se a transação real com `(recurrence_id, occurrence_date)` — chave única que impede duplicidade.
- "Saldo atual" considera transações realizadas até hoje; "saldo projetado" soma previsões e recorrências até o fim do mês.

---

## 5. Estrutura de diretórios

```
JULLIUS/
├── README.md
├── docs/ARQUITETURA.md
├── backend/
│   ├── app/
│   │   ├── main.py          # cria o app, middlewares, rotas
│   │   ├── config.py        # variáveis de ambiente (dev/test/prod)
│   │   ├── db.py            # engine/sessão
│   │   ├── models/          # tabelas SQLAlchemy
│   │   ├── schemas/         # entrada/saída Pydantic
│   │   ├── api/             # rotas HTTP
│   │   ├── services/        # regras de negócio e cálculos
│   │   ├── ai/              # provedores de IA + parser local
│   │   └── security/        # senha, sessão, CSRF, rate limit
│   ├── migrations/          # Alembic
│   ├── tests/
│   └── .env.example
└── frontend/                # React + Vite + PWA
```

---

## 6. Autenticação

1. Cadastro: e-mail + senha (mín. 10 caracteres) → hash Argon2id.
2. Login: verificação em tempo constante; **rate limit** por IP+e-mail; mensagem genérica ("e-mail ou senha incorretos").
3. Sessão: token aleatório de 256 bits em cookie `httpOnly`, `Secure` (produção), `SameSite=Lax`; no banco fica só o SHA-256 do token. Expira em 30 dias, renovação deslizante.
4. CSRF: cookie `julius_csrf` legível + cabeçalho `X-CSRF-Token` obrigatório em toda requisição que altera dados (double-submit).
5. Logout invalida a sessão no servidor.
6. Toda consulta filtra por `user_id` da sessão (isolamento entre usuários).

Por que não JWT? Sessão no servidor pode ser revogada na hora (logout, senha trocada) e não exige guardar token em `localStorage` (vulnerável a XSS).

---

## 7. Fluxo financeiro

```
Texto "gastei 45 no mercado"  ──► POST /quick-input/parse ──► proposta (tipo, valor, categoria, data…)
                                         │ IA (se configurada) ou parser local
                                         ▼
                            Usuário confirma / corrige / descarta
                                         ▼
                              POST /transactions  ──► audit_log
                                         │ correção de categoria ──► categorization_rules
                                         ▼
                 services/ledger calcula saldos, totais, faturas e projeções
```

---

## 8. Estratégia de IA

- Interface `AIProvider` com `complete_json()` (texto → JSON) e `extract_from_image()`.
- Implementações: `GeminiProvider` (padrão, gratuito), `OpenAICompatibleProvider` (OpenAI, Groq, OpenRouter, Ollama) e `NoAIProvider`.
- Escolha via `AI_PROVIDER` no `.env`. Chaves só no backend.
- **Parser local em português** (regex + dicionário + regras aprendidas) funciona sem IA e sem internet. A IA é uma melhoria, não uma dependência: se cair, o lançamento continua funcionando.
- Assistente: a pergunta vira uma *intenção* estruturada (métrica, período, categoria). O backend executa a consulta e calcula; a IA só redige a resposta a partir dos números. Sem dados suficientes → resposta explícita "não há dados suficientes".
- Projeções sempre rotuladas como **estimativa**.

## 9. Estratégia offline

- Service Worker guarda o app (abre sem internet).
- Leituras recentes (dashboard, contas, categorias, últimas transações) ficam em cache no IndexedDB.
- Lançamentos feitos offline vão para uma **fila (outbox)** no IndexedDB com UUID gerado no aparelho e aparecem como "pendente de sincronização".
- Ao reconectar, a fila é enviada em ordem. Criação é **idempotente** (mesmo UUID duas vezes = mesmo registro). Edições usam `version` (controle otimista): se o servidor tiver versão mais nova, o app mostra o conflito em vez de sobrescrever.
- Interpretação por IA offline cai no parser local.

## 10. Estratégia mobile

PWA com layout próprio para celular: barra de navegação inferior, botão "+" fixo para o Quick Input, formulários em tela cheia, alvos de toque ≥ 44 px. Desktop usa barra lateral e tabelas. Futuro: Capacitor para lojas.

## 11. Segurança

Argon2id · sessões revogáveis · CSRF · rate limit · Pydantic valida toda entrada · SQLAlchemy parametriza todas as queries (sem SQL injection) · React escapa saída (sem `dangerouslySetInnerHTML`) + CSP · cabeçalhos de segurança · erros internos nunca expostos (mensagem amigável + id de correlação no log) · `.env` fora do Git · logs sem senhas/tokens.

## 12. Roadmap

| Fase | Entrega | Status |
|---|---|---|
| 1 | Fundação (estrutura, config, app, testes rodando) | ✅ concluída |
| 2 | Banco: modelos, migrations, constraints, índices | ✅ 2 migrations (esquema inicial, anexos), upgrade/downgrade testados |
| 3 | Autenticação | ✅ Argon2id, sessão revogável, CSRF, rate limit |
| 4 | Cadastro financeiro: contas, cartões, categorias, transações, transferências, parcelas, recorrências | ✅ |
| 5 | Dashboard | ✅ |
| 6 | Quick Input | ✅ parser local + IA opcional |
| 7 | Categorização inteligente (aprendizado com correções) | ✅ aprende com correções e confirmações |
| 8 | Assistente IA | ✅ intenções por regras; IA só classifica/redige |
| 9 | Relatórios | ✅ dia/semana/mês/ano, comparação, projeção, CSV |
| 10 | OCR / multimodal | ✅ via IA multimodal (exige provedor configurado); testado com IA simulada |
| 11 | Mobile (PWA) | ✅ PWA instalável, layout próprio para celular |
| 12 | Offline / sincronização | ✅ fila IndexedDB idempotente, testada em E2E |
| 13 | Endurecimento de segurança | ✅ base pronta; ver pendências |
| 14 | Testes E2E | ✅ 68 backend + 21 unitários frontend + 10 E2E |
| 15 | Deploy | 🟡 Dockerfile + render.yaml prontos, não executados (Docker indisponível aqui) |

## 13. MVP (primeira versão utilizável)

Login · contas e cartões · categorias padrão + personalizadas · lançar receita/despesa/transferência · parcelado · recorrentes · histórico com filtros · Quick Input com parser local (IA opcional) · dashboard (saldo atual, mês, projetado, próximos vencimentos, categorias) · exportação CSV/JSON · histórico de alterações.

## 14. Pendências conhecidas (honestas)

| Item | Situação |
|---|---|
| PostgreSQL | Modelos e migrations usam só recursos portáveis, mas não foram executados num Postgres real. Fazer no primeiro deploy (Neon) e rodar a suíte com `DATABASE_URL` apontando para um banco de teste |
| Docker / Render | Arquivos prontos; build não testado nesta máquina |
| OCR com IA real | Fluxo completo testado com provedor simulado; precisa de uma chave Gemini para validar a qualidade da leitura |
| Gemini/OpenAI reais | Chamadas HTTP implementadas conforme as APIs públicas; validar com chave real |
| Exportação Excel/PDF nativos | CSV (abre no Excel) e impressão do relatório para PDF pelo navegador. Arquivos .xlsx/.pdf gerados pelo servidor ficam para depois |
| Importação de extratos (OFX/CSV de banco) | Não implementada |
| Notificações push de vencimento | Não implementadas (alertas aparecem no app) |
| Rate limit | Em memória (1 instância). Com várias instâncias, trocar por Redis |
