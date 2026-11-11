import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

const SUGGESTIONS = [
  "Explain the Anglo-Maratha wars and their key treaties",
  "What were the major causes and consequences of the Revolt of 1857?",
  "Describe the administrative structure of the Mauryan Empire",
  "Summarize the key differences between Bhakti and Sufi movements",
];

function formatBytes(bytes) {
  if (!bytes || bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}

function formatDate(timestamp) {
  if (!timestamp) return "";
  const d = new Date(timestamp * 1000);
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export default function App() {
  // Chat state
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef(null);

  // Knowledge base management state
  const [isKbOpen, setIsKbOpen] = useState(false);
  const [documents, setDocuments] = useState([]);
  const [kbLoading, setKbLoading] = useState(false);
  const [selectedFile, setSelectedFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [rebuilding, setRebuilding] = useState(false);
  const [stats, setStats] = useState({
    indexReady: false,
    vectorCount: 0,
    totalFiles: 0,
    totalSizeBytes: 0,
    s3Bucket: "",
  });
  const [toast, setToast] = useState(null); // { type: 'success' | 'error' | 'info', message: string }

  const fileInputRef = useRef(null);

  // Auto-scroll chat to bottom
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  // Initial load of documents and system health
  useEffect(() => {
    fetchKnowledgeBaseData();
  }, []);

  // Auto-dismiss toast
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 5000);
    return () => clearTimeout(timer);
  }, [toast]);

  function showToast(message, type = "info") {
    setToast({ message, type });
  }

  async function fetchKnowledgeBaseData() {
    setKbLoading(true);
    try {
      const [docsRes, healthRes] = await Promise.all([
        fetch(`${API_URL}/documents`).catch(() => null),
        fetch(`${API_URL}/health`).catch(() => null),
      ]);

      if (docsRes && docsRes.ok) {
        const docsData = await docsRes.json();
        setDocuments(docsData.documents || []);
        setStats((prev) => ({
          ...prev,
          totalFiles: docsData.total_files || 0,
          totalSizeBytes: docsData.total_size_bytes || 0,
          vectorCount: docsData.vector_count || prev.vectorCount,
          s3Bucket: docsData.s3_bucket || prev.s3Bucket,
        }));
      }

      if (healthRes && healthRes.ok) {
        const healthData = await healthRes.json();
        setStats((prev) => ({
          ...prev,
          indexReady: Boolean(healthData.index_ready),
          vectorCount: healthData.vector_count ?? prev.vectorCount,
        }));
      }
    } catch (err) {
      console.error("Failed to fetch knowledge base status:", err);
    } finally {
      setKbLoading(false);
    }
  }

  async function handleFileUpload(e) {
    e.preventDefault();
    if (!selectedFile) {
      showToast("Please choose a file to upload.", "error");
      return;
    }

    const formData = new FormData();
    formData.append("file", selectedFile);

    setUploading(true);
    try {
      const res = await fetch(`${API_URL}/upload`, {
        method: "POST",
        body: formData,
      });
      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail || `Upload failed with status ${res.status}`);
      }

      showToast(
        `File "${data.filename}" uploaded successfully! Remember to refresh the Vector DB to index it.`,
        "success"
      );
      setSelectedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      await fetchKnowledgeBaseData();
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setUploading(false);
    }
  }

  async function handleRebuildVectorStore() {
    if (rebuilding) return;

    setRebuilding(true);
    showToast("Rebuilding vector database... Chunking and embedding documents.", "info");

    try {
      const res = await fetch(`${API_URL}/rebuild-vectorstore`, {
        method: "POST",
      });
      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail || `Rebuild failed with status ${res.status}`);
      }

      showToast(
        `Vector DB updated successfully! ${data.vector_count} chunks indexed from ${data.document_count} documents.`,
        "success"
      );
      await fetchKnowledgeBaseData();
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setRebuilding(false);
    }
  }

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
    <div className="formal-rag-app">
      {/* Toast Notification */}
      {toast && (
        <div className={`formal-toast ${toast.type}`}>
          <div className="toast-content">
            <span className="toast-dot" />
            <span className="toast-msg">{toast.message}</span>
          </div>
          <button className="toast-close" onClick={() => setToast(null)}>
            ✕
          </button>
        </div>
      )}

      {/* Header Bar */}
      <header className="formal-header">
        <div className="header-left">
          <div className="brand-icon">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
              <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
            </svg>
          </div>
          <div>
            <div className="title-row">
              <h1 className="header-title">SSC CGL Study Intelligence</h1>
              <span className="badge badge-accent">History Domain</span>
            </div>
            <p className="header-subtitle">
              Retrieval-Augmented Generation Platform • FAISS Index + Groq LLM
            </p>
          </div>
        </div>

        <div className="header-actions">
          {/* Index Status Badge */}
          <div
            className={`status-pill ${rebuilding
              ? "status-rebuilding"
              : stats.indexReady
                ? "status-ready"
                : "status-offline"
              }`}
            title={`${stats.vectorCount} embeddings stored`}
          >
            <span className="status-indicator-dot" />
            <span>
              {rebuilding
                ? "Indexing..."
                : stats.indexReady
                  ? `Vector DB Ready (${stats.vectorCount} vectors)`
                  : "Vector DB Empty"}
            </span>
          </div>

          {/* Quick Refresh Button */}
          <button
            className="btn btn-outline"
            onClick={handleRebuildVectorStore}
            disabled={rebuilding}
            title="Rebuild and sync vector index with data repository"
          >
            <svg
              className={`btn-icon ${rebuilding ? "spin" : ""}`}
              width="15"
              height="15"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67" />
            </svg>
            <span>{rebuilding ? "Rebuilding..." : "Rebuild Vector DB"}</span>
          </button>

          {/* Knowledge Base Toggle Button */}
          <button
            className={`btn ${isKbOpen ? "btn-primary-active" : "btn-primary"}`}
            onClick={() => setIsKbOpen(!isKbOpen)}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <path d="M3 9h18M9 21V9" />
            </svg>
            <span>Knowledge Base</span>
            <span className="count-pill">{stats.totalFiles}</span>
          </button>
        </div>
      </header>

      {/* Main Workspace Layout */}
      <div className="main-workspace">
        {/* Chat Area */}
        <section className="chat-section">
          <main className="chat-container">
            {messages.length === 0 && (
              <div className="empty-state">
                <div className="empty-icon-wrap">
                  <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                    <circle cx="12" cy="12" r="10" />
                    <line x1="12" y1="16" x2="12" y2="12" />
                    <line x1="12" y1="8" x2="12.01" y2="8" />
                  </svg>
                </div>
                <h2>SSC CGL Exam Preparation Tutor</h2>
                <p>
                  Ask any question from the ingested history textbooks and notes.
                  All responses are synthesized strictly from retrieved context with citation provenance.
                </p>

                <div className="suggestions-grid">
                  <div className="suggestions-label">Recommended Queries:</div>
                  <div className="suggestions-list">
                    {SUGGESTIONS.map((item, idx) => (
                      <button
                        key={idx}
                        className="suggestion-chip"
                        onClick={() => send(item)}
                        disabled={loading}
                      >
                        <span className="chip-arrow">→</span>
                        <span>{item}</span>
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {messages.map((m, i) => (
              <div key={i} className={`chat-message-row ${m.role} ${m.error ? "has-error" : ""}`}>
                <div className="avatar">
                  {m.role === "assistant" ? "AI" : "YOU"}
                </div>
                <div className="message-card">
                  <div className="message-header">
                    <span className="sender-name">
                      {m.role === "assistant" ? "Tutor Assistant" : "Student Query"}
                    </span>
                  </div>
                  <div className="message-body">
                    {m.role === "assistant" ? (
                      <ReactMarkdown>{m.content}</ReactMarkdown>
                    ) : (
                      m.content
                    )}
                  </div>

                  {m.sources && m.sources.length > 0 && (
                    <details className="source-citations">
                      <summary>
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                          <polyline points="14 2 14 8 20 8" />
                          <line x1="16" y1="13" x2="8" y2="13" />
                          <line x1="16" y1="17" x2="8" y2="17" />
                        </svg>
                        <span>Retrieved Context ({m.sources.length} matching passages)</span>
                      </summary>
                      <div className="citations-list">
                        {m.sources.map((s, j) => (
                          <div key={j} className="citation-card">
                            <div className="citation-header">
                              <span className="citation-idx">Passage #{j + 1}</span>
                              <span className="citation-score">
                                Distance: {s.distance.toFixed(4)}
                              </span>
                            </div>
                            <div className="citation-snippet">{s.text}</div>
                          </div>
                        ))}
                      </div>
                    </details>
                  )}
                </div>
              </div>
            ))}

            {loading && (
              <div className="chat-message-row assistant">
                <div className="avatar">AI</div>
                <div className="message-card loading-card">
                  <div className="loading-dots">
                    <span />
                    <span />
                    <span />
                  </div>
                  <span className="loading-label">Searching vector space and synthesizing response...</span>
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </main>

          <footer className="composer-container">
            <div className="composer-wrapper">
              <textarea
                rows={1}
                className="composer-input"
                value={input}
                placeholder="Ask an exam question or topic analysis... (Press Enter to send)"
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onKeyDown}
                disabled={loading}
              />
              <button
                className="composer-send-btn"
                onClick={() => send()}
                disabled={loading || !input.trim()}
                title="Send query (Enter)"
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <line x1="22" y1="2" x2="11" y2="13" />
                  <polygon points="22 2 15 22 11 13 2 9 22 2" />
                </svg>
              </button>
            </div>
          </footer>
        </section>

        {/* Knowledge Base Side Drawer */}
        {isKbOpen && (
          <aside className="kb-drawer">
            <div className="kb-header">
              <div className="kb-title-block">
                <h3>Knowledge Base</h3>
                <span className="kb-subtitle">AWS S3 Storage & Vector Index</span>
              </div>
              <button
                className="close-drawer-btn"
                onClick={() => setIsKbOpen(false)}
                title="Close drawer"
              >
                ✕
              </button>
            </div>

            <div className="kb-content">
              {/* Card 1: Update Knowledge Base (Upload) */}
              <div className="kb-card">
                <div className="card-header">
                  <div className="card-title">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                      <polyline points="17 8 12 3 7 8" />
                      <line x1="12" y1="3" x2="12" y2="15" />
                    </svg>
                    <span>Update Knowledge Base</span>
                  </div>
                  <span className="card-badge">Data Ingestion</span>
                </div>
                <p className="card-desc">
                  Upload learning material (.pdf, .txt, .docx, .csv, .xlsx, .json). Files will be stored in AWS S3.
                </p>

                <form onSubmit={handleFileUpload} className="upload-form">
                  <div className="file-input-wrapper">
                    <input
                      type="file"
                      id="kb-file-upload"
                      ref={fileInputRef}
                      onChange={(e) => setSelectedFile(e.target.files[0] || null)}
                      accept=".pdf,.txt,.docx,.csv,.xlsx,.json"
                      disabled={uploading}
                    />
                    <label htmlFor="kb-file-upload" className="file-input-label">
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
                        <polyline points="13 2 13 9 20 9" />
                      </svg>
                      <span className="file-name-truncate">
                        {selectedFile ? selectedFile.name : "Select document to upload…"}
                      </span>
                      {selectedFile && (
                        <span className="file-size-tag">
                          {formatBytes(selectedFile.size)}
                        </span>
                      )}
                    </label>
                  </div>

                  <button
                    type="submit"
                    className="btn btn-primary btn-block"
                    disabled={uploading || !selectedFile}
                  >
                    {uploading ? (
                      <>
                        <span className="spinner-small" />
                        <span>Uploading...</span>
                      </>
                    ) : (
                      <>
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <line x1="12" y1="5" x2="12" y2="19" />
                          <line x1="5" y1="12" x2="19" y2="12" />
                        </svg>
                        <span>Update Knowledge Base</span>
                      </>
                    )}
                  </button>
                </form>
              </div>

              {/* Card 2: Vector DB Maintenance */}
              <div className="kb-card">
                <div className="card-header">
                  <div className="card-title">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <ellipse cx="12" cy="5" rx="9" ry="3" />
                      <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
                      <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
                    </svg>
                    <span>Vector DB Sync</span>
                  </div>
                  <span className={`status-pill-small ${stats.indexReady ? "ready" : "offline"}`}>
                    {stats.indexReady ? "Synchronized" : "Rebuild Needed"}
                  </span>
                </div>
                <p className="card-desc">
                  Sync all files from AWS S3 storage, chunk text, generate embeddings, and reload the FAISS index in memory.
                </p>

                <button
                  type="button"
                  className="btn btn-accent btn-block"
                  onClick={handleRebuildVectorStore}
                  disabled={rebuilding}
                >
                  {rebuilding ? (
                    <>
                      <span className="spinner-small" />
                      <span>Rebuilding Vector DB...</span>
                    </>
                  ) : (
                    <>
                      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67" />
                      </svg>
                      <span>Rebuild Vector DB</span>
                    </>
                  )}
                </button>
              </div>

              {/* Card 3: Document Inventory */}
              <div className="kb-card">
                <div className="card-header">
                  <div className="card-title">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                      <polyline points="14 2 14 8 20 8" />
                    </svg>
                    <span>Ingested Documents (AWS S3)</span>
                  </div>
                  <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
                    {stats.s3Bucket && (
                      <span className="card-badge" title={`S3 Bucket: ${stats.s3Bucket}`}>
                        s3://{stats.s3Bucket}
                      </span>
                    )}
                    <span className="card-badge">
                      {stats.totalFiles} files ({formatBytes(stats.totalSizeBytes)})
                    </span>
                  </div>
                </div>

                <div className="document-list">
                  {kbLoading ? (
                    <div className="kb-loading-state">Loading document inventory...</div>
                  ) : documents.length === 0 ? (
                    <div className="kb-empty-docs">
                      No documents found in the repository. Use the upload tool above to add study material.
                    </div>
                  ) : (
                    documents.map((doc, idx) => (
                      <div key={idx} className="doc-item">
                        <div className="doc-icon-col">
                          <span className="doc-ext-tag">{doc.extension.replace(".", "").toUpperCase()}</span>
                        </div>
                        <div className="doc-meta-col">
                          <div className="doc-name" title={doc.filename}>
                            {doc.filename}
                          </div>
                          <div className="doc-sub">
                            <span>{formatBytes(doc.size_bytes)}</span>
                            <span>•</span>
                            <span>{formatDate(doc.modified_at)}</span>
                          </div>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}
