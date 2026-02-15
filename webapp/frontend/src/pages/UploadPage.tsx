import { useState, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Upload, FileText, Cog, CheckCircle, AlertCircle } from "lucide-react";

const API = "/api";

interface UploadResult {
  session_id: string;
  file_name: string;
  file_type: string;
  status: string;
  message: string;
}

export default function UploadPage() {
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [results, setResults] = useState<UploadResult[]>([]);
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

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
      setResults((prev) => [data, ...prev]);
    } catch (e: any) {
      setError(e.message || "업로드 중 오류 발생");
    } finally {
      setUploading(false);
    }
  }, []);

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

      {results.length > 0 && (
        <div className="card">
          <div className="card-header">
            <h3>업로드 이력</h3>
          </div>
          <div className="card-body" style={{ padding: 0 }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>파일명</th>
                  <th>유형</th>
                  <th>상태</th>
                  <th>작업</th>
                </tr>
              </thead>
              <tbody>
                {results.map((r) => (
                  <tr key={r.session_id}>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <FileText size={16} color="var(--navy-light)" />
                        {r.file_name}
                      </div>
                    </td>
                    <td>
                      <span className="format-badge" style={{ fontSize: 11 }}>
                        {r.file_type.toUpperCase()}
                      </span>
                    </td>
                    <td>
                      <span className={`badge badge-${r.status === "processing" ? "processing" : "completed"}`}>
                        {r.status === "processing" ? "처리 중" : "완료"}
                      </span>
                    </td>
                    <td>
                      <button
                        className="btn btn-outline"
                        style={{ padding: "4px 12px", fontSize: 13 }}
                        onClick={() => navigate(`/results/${r.session_id}`)}
                      >
                        결과 보기
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
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
