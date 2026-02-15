import { useState, useRef, useEffect } from "react";
import { useParams } from "react-router-dom";
import { Send, Bot, User, Database } from "lucide-react";

const API = "/api";

interface Message {
  role: "user" | "bot";
  content: string;
  sql?: string;
  data?: any[];
}

export default function ChatPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "bot",
      content: `안녕하세요! SB선보 P&ID 도면 AI 어시스턴트입니다.\n\n도면 데이터에 대해 질문해주세요. 예시:\n- "전체 밸브 수는 몇 개인가요?"\n- "BUTTERFLY 밸브 목록을 보여주세요"\n- "10인치 밸브는 몇 개인가요?"\n- "용접 물량 합계를 알려주세요"${sessionId ? `\n\n현재 세션: ${sessionId}` : ""}`,
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || loading) return;

    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setLoading(true);

    try {
      const res = await fetch(`${API}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId || "", message: text }),
      });
      const data = await res.json();
      setMessages((prev) => [
        ...prev,
        {
          role: "bot",
          content: data.response,
          sql: data.sql_query || undefined,
          data: data.data || undefined,
        },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: "bot", content: "서버 연결에 실패했습니다. 잠시 후 다시 시도해주세요." },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h2 style={{ fontSize: 24, fontWeight: 700, color: "var(--navy)", marginBottom: 16 }}>
        <Bot size={24} style={{ marginRight: 8, verticalAlign: "middle" }} />
        AI 도면 분석 챗봇
      </h2>

      <div className="chat-container">
        <div className="chat-messages">
          {messages.map((msg, i) => (
            <div key={i} className={`chat-msg ${msg.role}`}>
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4, fontSize: 12, opacity: 0.7 }}>
                {msg.role === "user" ? <User size={14} /> : <Bot size={14} />}
                {msg.role === "user" ? "사용자" : "AI 어시스턴트"}
              </div>
              <div>{msg.content}</div>
              {msg.sql && (
                <div style={{ marginTop: 8 }}>
                  <div style={{ fontSize: 11, opacity: 0.6, display: "flex", alignItems: "center", gap: 4 }}>
                    <Database size={12} /> SQL 쿼리:
                  </div>
                  <div className="sql-block">{msg.sql}</div>
                </div>
              )}
              {msg.data && msg.data.length > 0 && (
                <div style={{ marginTop: 8, overflowX: "auto", maxHeight: 200 }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
                    <thead>
                      <tr>
                        {Object.keys(msg.data[0]).map((key) => (
                          <th key={key} style={{
                            padding: "4px 8px", textAlign: "left", borderBottom: "1px solid rgba(255,255,255,0.2)",
                            whiteSpace: "nowrap", fontSize: 10
                          }}>
                            {key}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {msg.data.slice(0, 10).map((row, ri) => (
                        <tr key={ri}>
                          {Object.values(row).map((val: any, ci) => (
                            <td key={ci} style={{ padding: "3px 8px", borderBottom: "1px solid rgba(255,255,255,0.1)" }}>
                              {String(val)}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {msg.data.length > 10 && (
                    <div style={{ fontSize: 11, opacity: 0.6, marginTop: 4 }}>
                      ... 외 {msg.data.length - 10}건 더
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
          {loading && (
            <div className="chat-msg bot">
              <div className="spinner" style={{ width: 20, height: 20, margin: "0 auto" }} />
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        <div className="chat-input-area">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && sendMessage()}
            placeholder="도면 데이터에 대해 질문하세요..."
            disabled={loading}
          />
          <button className="btn btn-primary" onClick={sendMessage} disabled={loading}>
            <Send size={16} /> 전송
          </button>
        </div>
      </div>
    </div>
  );
}
