# JULIUS

Assistente financeiro pessoal. Você escreve “gastei 45 no mercado” e o JULIUS transforma isso em um lançamento organizado, controla contas e cartões, avisa vencimentos, mostra relatórios e responde perguntas como “quanto ainda posso gastar este mês?” — sempre com números calculados a partir dos seus dados reais.

Tudo é gratuito: código aberto, banco local (SQLite) ou PostgreSQL no plano gratuito do Neon, e IA opcional pelo plano gratuito do Google Gemini.

## O que funciona hoje

| Área | Recursos |
|---|---|
| Visão geral | Saldo agora, entrou/saiu, fim do mês estimado, a pagar/receber, dívidas; gráfico do saldo (realizado + projeção), calendário financeiro, receitas × despesas, categorias, parcelamentos, recorrentes, metas e alertas |
| Futuros | Linha do tempo de tudo que vai entrar e sair (salário, contas, faturas, parcelas) **com o saldo depois de cada um**; atalhos para salário, conta, aluguel, assinatura, parcela, financiamento; pagar, confirmar, cancelar, pular |
| Status | Previsto, confirmado, pago e cancelado; **atrasado** é calculado (nunca fica desatualizado) |
| Dívidas | Empréstimos, financiamentos, carnês: restante, parcelas e próximo vencimento calculados; “paguei a parcela” |
| Documentos | Foto, câmera ou PDF de conta/boleto/comprovante → leitura (PDF e linha digitável **sem IA**; fotos com IA) → revisão → confirmar como lançamento e/ou recorrência |
| Lançamentos | Receita, despesa e transferência; edição com proteção contra conflito; exclusão com “desfazer” |
| Quick Input | Frase em português → proposta (tipo, valor, categoria, data, conta, parcelas, recorrência) para confirmar, corrigir ou ignorar. Funciona **sem IA** |
| Aprendizado | Correções de categoria viram regras; a próxima sugestão já usa sua preferência |
| Contas e cartões | Saldo por conta; cartão com limite, fechamento, vencimento, faturas e pagamento de fatura (transferência — sem contar a despesa duas vezes) |
| Parcelamento | R$ 1.200 em 12× = 12 parcelas de R$ 100 com vencimentos e faturas corretas; centavos que sobram ficam na 1ª parcela |
| Recorrências | Aluguel, salário, assinaturas: previsões automáticas, “Paguei/Recebi” e “Pular”, sem duplicar |
| Dashboard | Saldo disponível, entradas/saídas do mês, saldo previsto para o fim do mês, próximos vencimentos, categorias, últimas movimentações, metas, cartões, orçamentos e alertas |
| Relatórios | Dia, semana, mês e ano; comparação com o período anterior; por categoria; fixas × variáveis; maiores despesas; gráfico com tabela alternativa; projeção (rotulada como estimativa) |
| Assistente | Perguntas em português respondidas com dados reais (“quanto vou gastar até o fim do mês?”, “por que gastei mais?”, “quanto devo?”). Com IA: agente com ferramentas controladas; criar/alterar/excluir **só com sua confirmação** |
| Orçamentos e metas | Limite mensal por categoria (alerta em 80%), metas com valor mensal necessário |
| Offline | Abre sem internet (PWA); criar, editar e excluir offline entram numa fila (pendente → sincronizando → sincronizado; falhou → tentar de novo) |
| Sincronização | Computador (instalação local) ↔ servidor online ↔ celular, com versões e **conflitos decididos por você** |
| Computador | Executável `JULIUS.exe` (banco no próprio PC) — veja [desktop/README.md](desktop/README.md) |
| Dados | Exportação CSV, Excel, PDF (relatório do mês) e JSON; importação de extrato OFX/CSV com prévia e sem duplicar; restauração que nunca apaga; exclusão definitiva da conta |
| Histórico | Toda criação, edição, exclusão e troca de categoria registrada |

## Tecnologias

Backend **Python 3.12 + FastAPI + SQLAlchemy 2 + Alembic** · Frontend **React + TypeScript + Vite (PWA)**, TanStack Query, Dexie (IndexedDB), Recharts · Testes **pytest, Vitest, Playwright**. As escolhas e alternativas estão em [docs/ARQUITETURA.md](docs/ARQUITETURA.md).

## Instalação (Windows)

Pré-requisitos: Python 3.12+ e Node.js 22+ (ambos gratuitos; não precisam de administrador).

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1   # venv, dependências, banco, .env
powershell -ExecutionPolicy Bypass -File scripts\start.ps1   # compila e abre http://127.0.0.1:8010
```

> ⚠️ Não coloque o projeto (nem o ambiente Python) dentro do OneDrive/Dropbox: a sincronização corrompe o ambiente virtual e trava o banco SQLite. O `setup.ps1` cria o venv em `%USERPROFILE%\.venvs\julius`.

Linux/macOS: mesmos passos manualmente — `python -m venv`, `pip install -r backend/requirements-dev.txt`, `alembic upgrade head` (em `backend/`), `npm install` (em `frontend/`).

**No celular:** com o app publicado (veja Deploy), abra o endereço no navegador e use “Adicionar à tela inicial”. Ele passa a funcionar como aplicativo, inclusive offline.

## Configuração

Copie `backend/.env.example` para `backend/.env`. Principais variáveis:

| Variável | Padrão | Para quê |
|---|---|---|
| `APP_ENV` | `development` | `production` liga cookies seguros, HSTS e desliga a documentação da API |
| `SECRET_KEY` | — | **Obrigatória em produção** |
| `DATABASE_URL` | SQLite em `backend/data/julius.db` | Produção: `postgresql+psycopg://usuario:senha@host/banco?sslmode=require` |
| `TIMEZONE` | `America/Sao_Paulo` | Define o “hoje” (servidores na nuvem rodam em UTC) |
| `ALLOW_REGISTRATION` | `true` | Desligue depois de criar sua conta, se o app for só seu |
| `AI_PROVIDER` | `none` | `gemini` ou `openai` (qualquer API compatível: OpenAI, Groq, OpenRouter, Ollama local) |
| `GEMINI_API_KEY` | — | Chave gratuita em https://aistudio.google.com/apikey |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | — | Para provedores compatíveis com OpenAI |
| `AI_MODEL` | padrão do provedor | Ex.: `gemini-flash-latest` |
| `REGISTER_LIMIT_PER_HOUR`, `LOGIN_LIMIT_PER_15MIN`, `AI_LIMIT_PER_MINUTE` | 5 / 8 / 30 | Limites contra abuso |

Sem IA o JULIUS funciona por completo: o Quick Input e o assistente usam um interpretador local em português. A IA melhora frases incomuns, lê comprovantes e redige conselhos — **nunca** calcula valores.

## Banco de dados e migrations

```powershell
cd backend
alembic upgrade head          # aplica migrations (seguro rodar sempre)
alembic downgrade -1          # desfaz a última
alembic revision --autogenerate -m "descrição"   # após alterar app/models — revise o arquivo gerado
python -m app.cli backup      # cópia consistente do SQLite em ..\backups\
```

Regras: dinheiro sempre em centavos inteiros; saldos são calculados, nunca gravados; exclusões são lógicas (`deleted_at`); nenhuma migration apaga dados sem decisão explícita.

## Desenvolvimento

```powershell
powershell -File scripts\dev.ps1   # API com recarga (8010) + Vite em http://localhost:5173
```

Documentação interativa da API (fora de produção): http://127.0.0.1:8010/api/docs

## Testes

```powershell
cd backend;  & "$env:USERPROFILE\.venvs\julius\Scripts\python.exe" -m pytest      # 111 testes: finanças, futuros, dívidas, documentos, agente, sincronização, migrations
cd frontend; npx vitest run                                                       # 24 testes: dinheiro e fila offline
cd frontend; npx tsc --noEmit                                                     # tipos
cd backend;  python -m tests.perf_check                                           # desempenho com 20 mil lançamentos
```

**E2E** (Playwright usando o Edge instalado; 10 fluxos × desktop e celular, incluindo offline, documentos e assistente):

```powershell
# terminal 1 — servidor de teste com banco próprio e limites altos
cd backend; $env:DATABASE_URL="sqlite:///data/e2e.db"; $env:REGISTER_LIMIT_PER_HOUR="1000"
alembic upgrade head; uvicorn app.main:app --port 8011
# terminal 2
cd frontend; npx vite build; $env:E2E_BASE_URL="http://127.0.0.1:8011"; npx playwright test
```

## Inteligência artificial (opcional e gratuita)

1. Gere uma chave grátis em https://aistudio.google.com/apikey.
2. Em `backend/.env`: `AI_PROVIDER=gemini` e `GEMINI_API_KEY=...` (na versão de computador: `%LOCALAPPDATA%\JULIUS\julius.env`).
3. **Seu agente do Gemini:** o JULIUS usa o agente pela API do Gemini, no servidor (a chave nunca vai ao navegador). Cole as instruções do seu agente/Gem em Ajustes → IA (ou aponte `AI_AGENT_INSTRUCTIONS_FILE` para um arquivo). As regras de segurança do JULIUS continuam valendo: a IA só usa ferramentas de leitura liberadas e qualquer criação, alteração ou exclusão espera sua confirmação.

Perguntas comuns (saldo, gastos, vencimentos, dívidas…) são respondidas por regras locais na hora, sem gastar cota de IA; o agente entra nas perguntas abertas.

## Build e Deploy (gratuito)

`npx vite build` gera o PWA em `backend/static`; o FastAPI serve API e app na mesma origem (cookies seguros, sem CORS).

**Recomendado: Render (web service grátis) + Neon (PostgreSQL grátis)**

1. Crie um banco no [Neon](https://neon.tech) e copie a connection string (troque o prefixo para `postgresql+psycopg://`).
2. Suba o repositório para o GitHub e, no [Render](https://render.com), crie um *Blueprint* apontando para ele — o `render.yaml` e o `Dockerfile` já estão prontos.
3. Preencha `DATABASE_URL` (e `GEMINI_API_KEY`, se quiser IA). O `SECRET_KEY` é gerado automaticamente. As migrations rodam a cada deploy.
4. Crie sua conta no app e mude `ALLOW_REGISTRATION` para `false`.

Observação: no plano grátis o Render “dorme” após 15 min sem uso; o primeiro acesso seguinte leva ~1 min. Alternativa sem custo e sem espera: rodar no próprio PC (`scripts\start.ps1`) e acessar pelo celular na mesma rede Wi-Fi.

Ambientes: `development` (local), `staging` e `production` (mesmas proteções de produção) — escolha por `APP_ENV`.

## Segurança

Senhas com Argon2id · sessão em cookie `httpOnly`/`SameSite=Lax` (`Secure` em produção) com token guardado só como hash e revogável · proteção CSRF (double-submit) · rate limit em login, cadastro e IA · validação de toda entrada (Pydantic) · consultas parametrizadas (sem SQL injection) · CSP e cabeçalhos de segurança · isolamento entre usuários testado · uploads verificados pelo conteúdo, não pela extensão · CSV protegido contra injeção de fórmulas · erros sem detalhes internos (código de rastreio no log) · chaves de API só no servidor · `.env` fora do Git.

## Estrutura

```
backend/   app/{api,services,ai,models,security}, migrations/, tests/
frontend/  src/{pages,components,lib,styles}, e2e/
desktop/   launcher.py, julius.spec (executável para computador)
docs/      ARQUITETURA.md, ATUALIZACAO-2.md
scripts/   setup.ps1, start.ps1, dev.ps1
```
