import { Bot, Send } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { Button } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { useOnline } from "../lib/offline";
import { useAiStatus } from "../lib/queries";
import type { AssistantAnswer } from "../lib/types";

interface Msg {
  role: "user" | "assistant";
  content: string;
  estimate?: boolean;
  error?: boolean;
}

const SUGGESTIONS = [
  "Quanto gastei com combustível este mês?",
  "Quanto ainda posso gastar este mês?",
  "Qual foi minha maior categoria de gastos?",
  "Quais despesas fixas tenho?",
  "Quanto economizei nos últimos três meses?",
  "Quanto terei daqui a seis meses?",
  "Quais são os próximos vencimentos?",
];

export default function Assistant() {
  const online = useOnline();
  const ai = useAiStatus().data;
  const [messages, setMessages] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Bloco explícito: scrollIntoView pode retornar uma Promise, que o React trataria como cleanup
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, loading]);

  async function ask(question: string) {
    if (!question.trim() || loading) return;
    setMessages((m) => [...m, { role: "user", content: question }]);
    setText("");
    setLoading(true);
    try {
      const r = await api<AssistantAnswer>("/api/assistant/ask", { body: { question, conversation_id: conversationId } });
      setConversationId(r.conversation_id);
      setMessages((m) => [...m, { role: "assistant", content: r.answer, estimate: r.is_estimate }]);
    } catch (err) {
      setMessages((m) => [...m, { role: "assistant", content: errorMessage(err), error: true }]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Assistente</h1>
          <p>Pergunte sobre seu dinheiro. As respostas vêm dos seus lançamentos reais.</p>
        </div>
        {messages.length > 0 && (
          <Button
            size="small"
            variant="ghost"
            onClick={() => {
              setMessages([]);
              setConversationId(null);
            }}
          >
            Nova conversa
          </Button>
        )}
      </div>

      <section className="panel" style={{ minHeight: 360, display: "grid", alignContent: "space-between", gap: 16 }}>
        {messages.length === 0 ? (
          <div className="state" style={{ padding: "24px 0" }}>
            <div className="icon">
              <Bot size={24} />
            </div>
            <h3>Como posso ajudar?</h3>
            <p>Os números são calculados pelo sistema; projeções são sempre estimativas.</p>
            <div className="chips" style={{ justifyContent: "center", maxWidth: 640 }}>
              {SUGGESTIONS.map((s) => (
                <button key={s} className="chip" onClick={() => ask(s)} disabled={!online}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="chat" aria-live="polite">
            {messages.map((m, i) => (
              <div key={i} className={`bubble ${m.role}`} style={m.error ? { color: "var(--danger)" } : undefined}>
                {m.content}
                {m.estimate && (
                  <div style={{ marginTop: 6 }}>
                    <span className="badge warn">Estimativa</span>
                  </div>
                )}
              </div>
            ))}
            {loading && (
              <div className="bubble assistant muted" aria-label="Calculando">
                Calculando…
              </div>
            )}
            <div ref={endRef} />
          </div>
        )}

        <form
          className="quick"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            ask(text);
          }}
        >
          <input
            aria-label="Sua pergunta"
            placeholder={online ? "Ex.: quanto gastei com lazer em setembro?" : "O assistente precisa de internet"}
            value={text}
            maxLength={500}
            disabled={!online}
            onChange={(e) => setText(e.target.value)}
          />
          <Button type="submit" variant="accent" className="icon" aria-label="Enviar" loading={loading} disabled={!online}>
            {!loading && <Send size={18} />}
          </Button>
        </form>
        {ai && !ai.enabled && (
          <p className="small muted">
            Modo sem IA: entendo as perguntas mais comuns por regras. Configure um provedor (ex.: Gemini, gratuito) para conversas mais livres.
          </p>
        )}
      </section>
    </>
  );
}
