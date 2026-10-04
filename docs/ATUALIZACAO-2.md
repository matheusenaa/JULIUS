# JULIUS — Atualização 2: diagnóstico e plano

## Diagnóstico do projeto existente (04/10/2026)

| Área | Estado encontrado | Avaliação |
|---|---|---|
| Stack | FastAPI + SQLAlchemy 2 + Alembic / React 19 + TS + Vite PWA | Adequada; **mantida** |
| Banco | 12 tabelas, 2 migrations, dinheiro em centavos, UUID, soft delete | Sólido. Faltam: status além de pago/previsto, dívidas, controle de versão em todas as entidades sincronizáveis |
| Autenticação | Argon2id, sessão revogável, CSRF, rate limit | Mantida |
| Lançamentos | Status `paid`/`pending` apenas | Falta CONFIRMADO e CANCELADO; ATRASADO deve ser **calculado** (não gravado) para nunca ficar desatualizado |
| Projeção | `projected_balance` soma agregados | Correto, mas não mostra **a sequência** dos compromissos (linha do tempo) |
| Dashboard | Tela "Início" com cards e barras | Boa para o dia a dia; falta visão gráfica (evolução, calendário, dívidas, parcelamentos) |
| Dívidas | Inexistente (só compras parceladas) | Criar |
| Documentos | Anexos guardados no banco; OCR só com IA | Falta área própria, metadados, armazenamento plugável, leitura de PDF sem IA, compressão de imagem |
| IA | Interpreta texto e responde por intenções | Falta modo **agente** com ferramentas controladas e confirmação de ações |
| Offline | Fila só para **criar** lançamentos | Falta editar/excluir offline, estados da fila e resolução de conflito |
| Sincronização entre dispositivos | Servidor é a fonte da verdade; cliente só cria | Falta protocolo pull/push com versões para instalação local ↔ servidor online |
| Desktop | PWA instalável pelo navegador | Falta modo **local** (banco no próprio PC) |
| Bugs/gargalos conhecidos | Nenhum aberto; dashboard faz ~30 consultas (aceitável, medir com volume) | Medir antes de otimizar |

## Decisões

1. **Status:** `pending` (previsto), `confirmed`, `paid`, `canceled`. "Atrasado" = previsto/confirmado com data passada, calculado na consulta.
2. **Tipos de lançamento futuro** (salário, aluguel, assinatura, conta…) são *atalhos* que preenchem categoria e recorrência — não uma tabela nova.
3. **Dívidas** ganham tabela própria; pagamentos são lançamentos ligados à dívida. Restante, próxima parcela e data final são **calculados**.
4. **Linha do tempo financeira** única (`services/forecast.py`) alimenta projeção, calendário, alertas, assistente e dashboard — um só cálculo, sem divergência.
5. **Agente de IA:** ferramentas com permissões explícitas. Leitura executa direto; escrita/exclusão vira *ação pendente* que só o usuário confirma. O "agente do Gemini" entra pelas instruções (texto do agente) + API do Gemini no backend; a chave nunca vai ao navegador.
6. **Sincronização:** toda entidade tem `id` UUID, `version` e `synced_version`. Envio com `base_version`; divergência vira **conflito para o usuário decidir** — nunca sobrescrita silenciosa.
7. **Desktop:** avaliados Electron (≈150 MB, pesado), Tauri (leve, mas exige Rust + empacotar o Python) e PWA. Escolha: **PWA instalável** para uso online + **modo local** (executável único com o servidor e SQLite no PC, sincronizando com o servidor online). Tauri fica como evolução para ícone de bandeja e atualizações nativas.
8. **Identidade:** monograma "J" desenhado como símbolo de moeda (como o traço do $), referência sutil a quem sabe o preço de cada coisa. Lema: *"Cada centavo tem destino."*

## Ordem de execução

Migration → serviços (status, linha do tempo, dívidas, documentos, agente, sincronização) → APIs → frontend (Visão geral, Futuros, Dívidas, Documentos, agente, central de sincronização, onboarding, ajustes) → identidade → desktop → testes → desempenho → documentação.

## Resultado

| Item | Status | Verificação |
|---|---|---|
| Migrations 0003 (status, dívidas, versões, documentos, ações da IA, sincronização) e 0004 (índice) | ✅ | upgrade → downgrade → upgrade em cópia do banco real, dados preservados |
| Linha do tempo / projeção / calendário / alertas | ✅ | exemplo do briefing (2.500 → 3.350) testado evento a evento |
| Status previsto/confirmado/pago/cancelado, atrasado calculado | ✅ | testes de saldo, listas e projeção |
| Salário previsto → recebido | ✅ | não entra como receita antes de confirmado |
| Dívidas (restante, parcelas, próxima, quitada) | ✅ | Notebook 12×250 com 5 pagas → R$ 1.750 |
| Visão geral (gráficos, calendário, dívidas, parcelamentos) | ✅ | E2E desktop e celular, revisão visual |
| Documentos: PDF/boleto sem IA, foto com IA, revisão e confirmação | ✅ | boleto FEBRABAN com dígitos verificadores; uploads maliciosos/interrompidos rejeitados |
| Agente: ferramentas controladas, escrita só com confirmação, falha da IA cai para regras | ✅ | testes com IA simulada, inclusive acesso a dados de outro usuário (bloqueado) |
| Sincronização local ↔ online com conflitos | ✅ | dois bancos reais em teste: união de categorias, ida e volta, conflito, exclusão, queda de rede |
| Fila offline com edições/exclusões e conflito no celular | ✅ | testes unitários + E2E |
| Desktop | ✅ | `JULIUS.exe` gerado (58 MB) e testado: cria banco, migra, serve o app |
| Desempenho | ✅ | 20 mil lançamentos: Visão geral 12,5 s → 0,77 s (índice de cobertura + cache por requisição) |
| Onboarding, ajustes (moeda, notificações, IA, privacidade, exclusão de conta) | ✅ | E2E do onboarding |
| Importação OFX/CSV, exportação Excel/PDF | ✅ | testes |

### Bugs reais encontrados pelos testes e corrigidos
- Sincronização sobrescrevia em silêncio uma edição local feita logo após um sincronismo (marca interna não era limpa).
- Sem internet, a sincronização estourava com erro cru em vez de "sem conexão".
- A leitura da linha digitável juntava o ano da linha anterior do PDF.
- Migration no SQLite era desfeita sem aviso (transação implícita aberta por PRAGMA).
- "Preencher manualmente" não fazia nada quando o documento não era legível.

### Pendências honestas
- Gemini real: implementado pelo endpoint oficial compatível com OpenAI; validar com chave real.
- PostgreSQL/Docker ainda não executados nesta máquina.
- Notificações: aviso do navegador quando o app abre; push com o app fechado exige um serviço agendado (fica para o deploy).
- Anexos (arquivos) não entram na sincronização entre dispositivos — só os dados.
- Tauri (ícone na bandeja, atualização automática) fica como evolução do executável atual.
