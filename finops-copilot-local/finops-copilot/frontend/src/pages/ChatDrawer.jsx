import { useState, useRef, useEffect } from "react";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "../components/ui/sheet";
import { API } from "../lib/api";
import { PaperPlaneRight, Sparkle, User, Wrench } from "@phosphor-icons/react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import "./ChatMarkdown.css";

// Tabelas largas rolam dentro da própria mensagem; links abrem em nova aba
const MD_COMPONENTS = {
  table: ({ node, ...props }) => <div className="overflow-x-auto my-2"><table {...props} /></div>,
  a: ({ node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" />,
};

const SUGGESTIONS = [
  "Top 5 serviços mais caros esse mês",
  "Quanto economizaria desligando dev à noite?",
  "Custo de Storage por subscription",
  "Quais VMs estão ociosas há mais de 30 dias?",
];

export default function ChatDrawer({ open, onOpenChange }) {
  const [messages, setMessages] = useState([
    { role: "assistant", content: "Oi! Sou seu copiloto FinOps. Pergunte qualquer coisa sobre seus custos e recomendações da Azure." },
  ]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [toolInFlight, setToolInFlight] = useState(null);
  const scrollRef = useRef(null);
  const sessionRef = useRef(Math.random().toString(36).slice(2));

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, toolInFlight]);

  const send = async (text) => {
    const msg = (text || input).trim();
    if (!msg || streaming) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", content: msg }, { role: "assistant", content: "" }]);
    setStreaming(true);

    try {
      const token = localStorage.getItem("finops_token");
      const res = await fetch(`${API}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ message: msg, session_id: sessionRef.current }),
      });
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const chunks = buf.split("\n\n");
        buf = chunks.pop();
        for (const c of chunks) {
          if (!c.startsWith("data: ")) continue;
          try {
            const ev = JSON.parse(c.slice(6));
            if (ev.type === "text") {
              setMessages((m) => {
                const copy = [...m];
                copy[copy.length - 1] = { ...copy[copy.length - 1], content: copy[copy.length - 1].content + ev.content };
                return copy;
              });
            } else if (ev.type === "tool_start") {
              setToolInFlight(ev.name);
            } else if (ev.type === "done") {
              setToolInFlight(null);
            } else if (ev.type === "error") {
              setMessages((m) => {
                const copy = [...m];
                copy[copy.length - 1] = { role: "assistant", content: `Erro: ${ev.content}` };
                return copy;
              });
            }
          } catch {}
        }
      }
    } catch (e) {
      setMessages((m) => {
        const copy = [...m];
        copy[copy.length - 1] = { role: "assistant", content: "Erro de conexão com o Copilot." };
        return copy;
      });
    } finally {
      setStreaming(false);
      setToolInFlight(null);
    }
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-full sm:w-[440px] bg-[#0d0d0e] border-l border-white/10 p-0 flex flex-col ai-glow"
        data-testid="chat-drawer"
      >
        <SheetHeader className="p-5 border-b border-white/5">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-full bg-[#0052CC] flex items-center justify-center">
              <Sparkle size={17} weight="fill" color="#fff"/>
            </div>
            <div>
              <SheetTitle className="text-left font-display text-base tracking-tight">FinOps Copilot</SheetTitle>
              <SheetDescription className="text-[10px] text-gray-500 uppercase tracking-widest">Assistente de custos · function-calling</SheetDescription>
            </div>
          </div>
        </SheetHeader>

        {/* Messages */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto p-5 space-y-4" data-testid="chat-messages">
          {messages.map((m, i) => (
            <div key={i} className={`flex gap-3 ${m.role === "user" ? "justify-end" : ""}`}>
              {m.role === "assistant" && (
                <div className="w-7 h-7 rounded-full bg-[#0052CC]/20 border border-[#0052CC]/40 flex items-center justify-center shrink-0 mt-0.5">
                  <Sparkle size={12} className="text-[#5B8DEF]" weight="fill" />
                </div>
              )}
              <div
                className={`chat-msg text-sm leading-relaxed ${
                  m.role === "user"
                    ? "max-w-[85%] bg-[#FFD60A] text-black rounded-lg px-3.5 py-2.5 font-medium"
                    : "chat-md min-w-0 flex-1 text-gray-200"
                }`}
              >
                {m.content ? (
                  m.role === "user" ? m.content : (
                    <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD_COMPONENTS}>{m.content}</ReactMarkdown>
                  )
                ) : (streaming && i === messages.length - 1 ? <span className="text-gray-500 animate-pulse">Pensando…</span> : "")}
              </div>
              {m.role === "user" && (
                <div className="w-7 h-7 rounded-full bg-white/10 flex items-center justify-center shrink-0 mt-0.5">
                  <User size={12} className="text-gray-300"/>
                </div>
              )}
            </div>
          ))}
          {toolInFlight && (
            <div className="flex items-center gap-2 text-xs text-gray-500 pl-10">
              <Wrench size={12} className="animate-pulse"/> Consultando <span className="font-mono-tab">{toolInFlight}</span>…
            </div>
          )}
        </div>

        {/* Suggestions */}
        {messages.length <= 1 && (
          <div className="px-5 pb-2 grid grid-cols-1 gap-2">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                data-testid={`chat-suggestion-${s.slice(0,10)}`}
                onClick={() => send(s)}
                disabled={streaming}
                className="text-left text-xs text-gray-300 border border-white/10 rounded-md px-3 py-2 hover:bg-white/[0.04] hover:border-white/20 transition-colors"
              >
                {s}
              </button>
            ))}
          </div>
        )}

        {/* Input */}
        <div className="p-4 border-t border-white/5">
          <form
            onSubmit={(e) => { e.preventDefault(); send(); }}
            className="flex items-center gap-2 bg-[#141415] border border-white/10 rounded-md focus-within:border-white/30"
          >
            <input
              data-testid="chat-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Pergunte algo sobre seus custos…"
              disabled={streaming}
              className="flex-1 bg-transparent px-4 py-2.5 text-sm outline-none placeholder:text-gray-600"
            />
            <button
              data-testid="chat-send"
              type="submit"
              disabled={streaming || !input.trim()}
              className="p-2 mr-1 rounded bg-[#0052CC] hover:bg-[#1a6ce0] disabled:opacity-30 text-white transition-colors"
            >
              <PaperPlaneRight size={14} weight="fill"/>
            </button>
          </form>
        </div>
      </SheetContent>
    </Sheet>
  );
}
