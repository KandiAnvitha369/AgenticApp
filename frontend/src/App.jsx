import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";

// Backend address. Change here if your API runs elsewhere.
const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

const SUGGESTIONS = [
  "Explain the Anglo-Maratha wars",
  "What was the Revolt of 1857?",
  "Key features of the Mauryan administration",
];

export default function App() {
  const [messages, setMessages] = useState([]); // {role: "user"|"assistant", content, sources?, error?}
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function send(text) {
    const question = (text ?? input).trim();
    if (!question || loading) return;

    const history = messages
      .filter((m) => !m.error)
      .map((m) => ({ role: m.role, content: m.content }));

    setMessages((prev) => [...prev, { role: "user", content: question }]);
    setInput("");
    setLoading(true);

    try {
      const res = await fetch(`${API_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: question, history }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || `Server error ${res.status}`);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: data.answer, sources: data.sources },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `Error: ${err.message}`, error: true },
      ]);
    } finally {
      setLoading(false);
    }
  }

  function onKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  return (
    <div className="app">
      <header className="header">
        <h1>Study Bot</h1>
        <span className="tag">History</span>
      </header>

      <main className="chat">
        {messages.length === 0 && (
          <div className="empty">
            <p>Ask anything from your study material.</p>
            <div className="suggestions">
              {SUGGESTIONS.map((s) => (
                <button key={s} onClick={() => send(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role} ${m.error ? "error" : ""}`}>
            <div className="bubble">
              {m.role === "assistant" ? (
                <ReactMarkdown>{m.content}</ReactMarkdown>
              ) : (
                m.content
              )}
              {m.sources?.length > 0 && (
                <details className="sources">
                  <summary>Sources ({m.sources.length})</summary>
                  {m.sources.map((s, j) => (
                    <p key={j}>{s.text}</p>
                  ))}
                </details>
              )}
            </div>
          </div>
        ))}

        {loading && (
          <div className="msg assistant">
            <div className="bubble typing">Thinking…</div>
          </div>
        )}
        <div ref={bottomRef} />
      </main>

      <footer className="composer">
        <textarea
          rows={1}
          value={input}
          placeholder="Type your question… (Enter to send)"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
        />
        <button onClick={() => send()} disabled={loading || !input.trim()}>
          Send
        </button>
      </footer>
    </div>
  );
}
