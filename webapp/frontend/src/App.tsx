import { Routes, Route, NavLink } from "react-router-dom";
import { Ship, Upload, BarChart3, MessageSquare } from "lucide-react";
import UploadPage from "./pages/UploadPage";
import ResultsPage from "./pages/ResultsPage";
import ChatPage from "./pages/ChatPage";

export default function App() {
  return (
    <div className="app-container">
      <header className="header">
        <div className="header-left">
          <div className="header-logo">
            <Ship size={22} style={{ marginRight: 8, verticalAlign: "middle" }} />
            SB SUNBO
          </div>
          <span className="header-title">P&ID 도면 AI 변환 시스템</span>
        </div>
        <nav className="header-nav">
          <NavLink to="/" className={({ isActive }) => isActive ? "active" : ""} end>
            <Upload size={16} style={{ marginRight: 4, verticalAlign: "middle" }} />
            업로드
          </NavLink>
          <NavLink to="/results" className={({ isActive }) => isActive ? "active" : ""}>
            <BarChart3 size={16} style={{ marginRight: 4, verticalAlign: "middle" }} />
            결과
          </NavLink>
          <NavLink to="/chat" className={({ isActive }) => isActive ? "active" : ""}>
            <MessageSquare size={16} style={{ marginRight: 4, verticalAlign: "middle" }} />
            AI 챗봇
          </NavLink>
        </nav>
      </header>

      <div className="main-content">
        <Routes>
          <Route path="/" element={<UploadPage />} />
          <Route path="/results" element={<ResultsPage />} />
          <Route path="/results/:sessionId" element={<ResultsPage />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/chat/:sessionId" element={<ChatPage />} />
        </Routes>
      </div>
    </div>
  );
}
