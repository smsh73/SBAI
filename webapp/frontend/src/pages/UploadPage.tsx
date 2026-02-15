import { useState, useRef, useCallback, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Upload, FileText, Cog, CheckCircle, AlertCircle, Clock, ChevronRight } from "lucide-react";

const API = "/api";

interface UploadResult {
  session_id: string;
  file_name: string;
  file_type: string;
  status: string;
  message: string;
}

interface SessionItem {
  id: string;
  created_at: string;
  file_type: string;
  file_name: string;
  status: string;
}

const FILE_TYPE_LABELS: Record<string, string> = {
  dxf: "DXF",
  pid: "P&ID",
  pipe_bom: "PIPE BOM",
  pdf: "PDF",
};

function formatDate(dateStr: string): string {
  try {
    const d = new Date(dateStr);
    const month = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    const hours = String(d.getHours()).padStart(2, "0");
    const mins = String(d.getMinutes()).padStart(2, "0");
    return `${month}/${day} ${hours}:${mins}`;
  } catch {
    return dateStr;
  }
}

export default function UploadPage() {
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  // 페이지 로드 시 세션 목록 가져오기
  useEffect(() => {
    fetch(`${API}/sessions`)
      .then((res) => res.json())
      .then((data) => setSessions(data.sessions || []))
      .catch(() => {});
  }, []);

  const uploadFile = useCallback(async (file: File) => {
    setUploading(true);
    setError("");
    const form = new FormData();
    form.append("file", file);

    try {
      const res = await fetch(`${API}/upload`, { method: "POST", body: form });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({ detail: "업로드 실패" }));
        throw new Error(errData.detail || "업로드 실패");
      }
      const data: UploadResult = await res.json();
      // 새 세션을 목록 상단에 추가
      setSessions((prev) => [
        {
          id: data.session_id,
          created_at: new Date().toISOString(),
          file_type: data.file_type,
          file_name: data.file_name,
          status: data.status,
        },
        ...prev,
      ]);
      // 바로 결과 페이지로 이동
      navigate(`/results/${data.session_id}`);
    } catch (e: any) {
      setError(e.message || "업로드 중 오류 발생");
    } finally {
      setUploading(false);
    }
  }, [navigate]);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const files = e.dataTransfer.files;
      if (files.length > 0) uploadFile(files[0]);
    },
    [uploadFile]
  );

  const onFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = e.target.files;
      if (files && files.length > 0) uploadFile(files[0]);
    },
    [uploadFile]
  );

  const getStatusBadge = (status: string) => {
    if (status === "completed") {
      return (
        <span className="badge badge-completed" style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
          <CheckCircle size={12} /> 완료
        </span>
      );
    }
    if (status === "processing") {
      return (
        <span className="badge badge-processing" style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
          <Cog size={12} className="spinner" /> 처리 중
        </span>
      );
    }
    if (status.startsWith("error")) {
      return (
        <span className="badge" style={{ background: "#FEE2E2", color: "#DC2626", display: "inline-flex", alignItems: "center", gap: 4 }}>
          <AlertCircle size={12} /> 오류
        </span>
      );
    }
    return <span className="badge">{status}</span>;
  };

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ fontSize: 24, fontWeight: 700, color: "var(--navy)" }}>
          도면 파일 업로드
        </h2>
        <p style={{ color: "var(--gray-500)", marginTop: 4 }}>
          DXF, P&ID PDF, PIPE BOM PDF 파일을 업로드하면 AI가 자동으로 분석합니다
        </p>
      </div>

      <div className="card" style={{ marginBottom: 24 }}>
        <div
          className={`upload-zone ${dragging ? "dragging" : ""}`}
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          onClick={() => fileRef.current?.click()}
        >
          <div className="icon">
            {uploading ? <Cog size={64} className="spinner" /> : <Upload size={64} />}
          </div>
          <h3>{uploading ? "업로드 중..." : "파일을 드래그하거나 클릭하여 선택"}</h3>
          <p>도면 파일을 여기에 놓으세요</p>
          <div className="formats">
            <span className="format-badge">DXF</span>
            <span className="format-badge">P&ID PDF</span>
            <span className="format-badge">PIPE BOM PDF</span>
          </div>
          <input
            ref={fileRef}
            type="file"
            accept=".dxf,.pdf"
            onChange={onFileSelect}
            style={{ display: "none" }}
          />
        </div>
      </div>

      {error && (
        <div className="card" style={{ marginBottom: 16, borderColor: "var(--error)" }}>
          <div className="card-body" style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--error)" }}>
            <AlertCircle size={20} /> {error}
          </div>
        </div>
      )}

      {sessions.length > 0 && (
        <div className="card" style={{ marginBottom: 24 }}>
          <div className="card-header">
            <h3>처리 이력</h3>
          </div>
          <div className="card-body" style={{ padding: 0 }}>
            <div className="session-list">
              {sessions.map((s) => (
                <div
                  key={s.id}
                  className="session-item"
                  onClick={() => navigate(`/results/${s.id}`)}
                >
                  <div className="session-icon">
                    <FileText size={24} color="var(--navy-light)" />
                  </div>
                  <div className="session-info">
                    <div className="session-name">{s.file_name}</div>
                    <div className="session-meta">
                      <span className="format-badge" style={{ fontSize: 10, padding: "1px 6px" }}>
                        {FILE_TYPE_LABELS[s.file_type] || s.file_type.toUpperCase()}
                      </span>
                      <span style={{ color: "var(--gray-400)", fontSize: 12, display: "inline-flex", alignItems: "center", gap: 3 }}>
                        <Clock size={11} /> {formatDate(s.created_at)}
                      </span>
                      {getStatusBadge(s.status)}
                    </div>
                  </div>
                  <ChevronRight size={20} color="var(--gray-300)" />
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      <div className="card" style={{ marginTop: 24 }}>
        <div className="card-header">
          <h3>지원 파일 형식</h3>
        </div>
        <div className="card-body">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 16 }}>
            <div style={{ padding: 16, background: "var(--gray-50)", borderRadius: 8 }}>
              <h4 style={{ color: "var(--navy)", marginBottom: 8 }}>DXF 파일</h4>
              <ul style={{ fontSize: 13, color: "var(--gray-500)", paddingLeft: 16 }}>
                <li>3D/2D AutoCAD 도면 파일</li>
                <li>4개 뷰 자동 분리 렌더링</li>
                <li>세부 치수 역계산 (DIMLFAC)</li>
                <li>2D 도면 파일 자동 생성</li>
              </ul>
            </div>
            <div style={{ padding: 16, background: "var(--gray-50)", borderRadius: 8 }}>
              <h4 style={{ color: "var(--navy)", marginBottom: 8 }}>P&ID PDF</h4>
              <ul style={{ fontSize: 13, color: "var(--gray-500)", paddingLeft: 16 }}>
                <li>밸브 태그 자동 인식 추출</li>
                <li>규격/재질 정보 파싱</li>
                <li>VALVE-LIST Excel 자동 생성</li>
              </ul>
            </div>
            <div style={{ padding: 16, background: "var(--gray-50)", borderRadius: 8 }}>
              <h4 style={{ color: "var(--navy)", marginBottom: 8 }}>PIPE BOM PDF</h4>
              <ul style={{ fontSize: 13, color: "var(--gray-500)", paddingLeft: 16 }}>
                <li>파이프 피스 자동 추출</li>
                <li>용접 항목 물량 취합</li>
                <li>4개 시트 BOM Excel 생성</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
