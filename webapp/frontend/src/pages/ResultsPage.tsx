import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  Download, Image, FileSpreadsheet, X, ZoomIn,
  ChevronLeft, ChevronRight, RefreshCw, Package, Wrench,
  Eye, Layers, Activity
} from "lucide-react";

const API = "/api";

interface FileEntry { name: string; path: string; size: number }

interface BomPage {
  page: number;
  pipe_pieces: string[];
  weld_count: number;
  weld_items: string[];
  dimensions_mm: number[];
  has_loose: boolean;
  is_cover?: boolean;
}

interface VlmBomItem {
  letter_code?: string;
  item_no?: string;
  quantity?: string | number;
  size_inches?: string;
  description?: string;
  material_spec?: string;
  weight_kg?: number;
  remarks?: string;
}

interface VlmPageData {
  page: number;
  drawing_number?: string;
  line_no?: string;
  pipe_no?: string;
  line_description?: string;
  pipe_group?: string;
  pipe_pieces?: any[];
  components?: any[];
  weld_points?: any[];
  dimensions_mm?: any[];
  bom_table?: VlmBomItem[];
  cut_lengths?: { cut_no: number; length_mm: number }[];
  total_weld_count?: number;
  shop_weld_count?: number;
  field_weld_count?: number;
  has_loose_parts?: boolean;
  drawing_analysis_ok?: boolean;
  table_analysis_ok?: boolean;
  confidence?: number;
  drawing_info?: any;
  bom_totals?: any;
}

interface VlmBomPreview {
  total_pages: number;
  total_pipe_pieces: number;
  total_components: number;
  total_weld_points: number;
  total_bom_items: number;
  total_dimensions: number;
  total_cut_lengths: number;
  valve_summary: Record<string, number>;
  fitting_summary: Record<string, number>;
  unique_line_nos?: string[];
  pages: VlmPageData[];
}

interface SessionResult {
  session_id: string;
  status: string;
  file_type: string;
  file_name: string;
  files: FileEntry[];
  images: FileEntry[];
  excel_files: FileEntry[];
  json_files: FileEntry[];
  preview: {
    dimensions?: any;
    valves?: { total: number; by_type: Record<string, number>; by_size: Record<string, number>; sample: any[] };
    pipe_bom?: {
      total_pages: number;
      content_pages: number;
      total_pieces: number;
      total_welds: number;
      total_length_mm: number;
      loose_count: number;
      pages: BomPage[];
    };
    vlm_bom?: VlmBomPreview;
    symbols?: { total: number; by_category: Record<string, number>; sample: any[] };
    vlm_stats?: any;
  };
}

const IMG_PAGE_SIZE = 12;
const BOM_PAGE_SIZE = 20;
const VLM_PAGE_SIZE = 10;

export default function ResultsPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<SessionResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [modalImage, setModalImage] = useState<string | null>(null);
  const [inputSession, setInputSession] = useState(sessionId || "");
  const [imgPage, setImgPage] = useState(0);
  const [bomPage, setBomPage] = useState(0);
  const [vlmPage, setVlmPage] = useState(0);
  const [expandedVlmPage, setExpandedVlmPage] = useState<number | null>(null);
  const [vlmTab, setVlmTab] = useState<"bom" | "drawing" | "index">("index");

  const loadResults = useCallback(async (sid: string) => {
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${API}/results/${sid}`);
      if (!res.ok) throw new Error("세션을 찾을 수 없습니다");
      const result = await res.json();
      setData(result);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (sessionId) loadResults(sessionId);
  }, [sessionId, loadResults]);

  useEffect(() => {
    if ((data?.status === "processing" || data?.status === "vlm_analyzing") && sessionId) {
      const timer = setInterval(() => loadResults(sessionId), 3000);
      return () => clearInterval(timer);
    }
  }, [data?.status, sessionId, loadResults]);

  const handleLookup = () => {
    if (inputSession.trim()) navigate(`/results/${inputSession.trim()}`);
  };

  if (!sessionId) {
    return (
      <div>
        <h2 style={{ fontSize: 24, fontWeight: 700, color: "var(--navy)", marginBottom: 16 }}>
          결과 조회
        </h2>
        <div className="card">
          <div className="card-body">
            <p style={{ marginBottom: 16, color: "var(--gray-500)" }}>
              세션 ID를 입력하여 처리 결과를 조회하세요
            </p>
            <div style={{ display: "flex", gap: 8 }}>
              <input
                type="text"
                value={inputSession}
                onChange={(e) => setInputSession(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleLookup()}
                placeholder="세션 ID 입력..."
                style={{
                  flex: 1, padding: "10px 16px", border: "1px solid var(--gray-300)",
                  borderRadius: 8, fontSize: 14, fontFamily: "inherit"
                }}
              />
              <button className="btn btn-primary" onClick={handleLookup}>조회</button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  const totalImgPages = data ? Math.ceil(data.images.length / IMG_PAGE_SIZE) : 0;
  const visibleImages = data ? data.images.slice(imgPage * IMG_PAGE_SIZE, (imgPage + 1) * IMG_PAGE_SIZE) : [];
  const bomData = data?.preview.pipe_bom?.pages || [];
  const totalBomPages = Math.ceil(bomData.length / BOM_PAGE_SIZE);
  const visibleBom = bomData.slice(bomPage * BOM_PAGE_SIZE, (bomPage + 1) * BOM_PAGE_SIZE);
  const vlmData = data?.preview.vlm_bom?.pages || [];
  const totalVlmPages = Math.ceil(vlmData.length / VLM_PAGE_SIZE);
  const visibleVlm = vlmData.slice(vlmPage * VLM_PAGE_SIZE, (vlmPage + 1) * VLM_PAGE_SIZE);

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 24 }}>
        <button className="btn btn-outline" onClick={() => navigate("/")}>
          <ChevronLeft size={16} /> 돌아가기
        </button>
        <div style={{ flex: 1 }}>
          <h2 style={{ fontSize: 20, fontWeight: 700, color: "var(--navy)" }}>
            {data?.file_name || "로딩 중..."}
          </h2>
          <p style={{ fontSize: 13, color: "var(--gray-500)" }}>세션: {sessionId}</p>
        </div>
        {data && (
          <span className={`badge badge-${
            data.status === "completed" ? "completed" :
            data.status.startsWith("error") ? "error" : "processing"
          }`}>
            {data.status === "completed" ? "완료" :
             data.status === "vlm_analyzing" ? "VLM 분석 중..." :
             data.status.startsWith("error") ? "오류" : "처리 중"}
          </span>
        )}
        <button className="btn btn-outline" onClick={() => loadResults(sessionId)}>
          <RefreshCw size={16} />
        </button>
      </div>

      {loading && !data && <div className="spinner" />}
      {error && <div className="card"><div className="card-body" style={{ color: "var(--error)" }}>{error}</div></div>}

      {data?.status === "processing" && (
        <div className="card" style={{ marginBottom: 24 }}>
          <div className="card-body" style={{ textAlign: "center", padding: 40 }}>
            <div className="spinner" />
            <p style={{ marginTop: 16, color: "var(--gray-500)" }}>AI가 도면을 분석하고 있습니다...</p>
          </div>
        </div>
      )}

      {data?.status === "vlm_analyzing" && (
        <div className="card" style={{ marginBottom: 24 }}>
          <div className="card-body" style={{ textAlign: "center", padding: 40 }}>
            <div className="spinner" />
            <p style={{ marginTop: 16, color: "var(--gold)" }}>VLM(Vision Language Model)으로 도면을 정밀 분석하고 있습니다...</p>
            <p style={{ fontSize: 13, color: "var(--gray-500)" }}>페이지당 약 30-40초 소요됩니다</p>
          </div>
        </div>
      )}

      {data && (data.status === "completed" || data.preview.vlm_bom) && (
        <>
          {/* 통계 요약 카드 */}
          {(data.preview.valves || data.preview.pipe_bom || data.preview.vlm_bom || data.preview.dimensions) && (
            <div className="stats-grid" style={{ marginBottom: 24 }}>
              {data.preview.vlm_bom && (
                <>
                  <div className="stat-card" style={{ borderLeft: "4px solid var(--navy)" }}>
                    <div className="value">{data.preview.vlm_bom.total_pages}</div>
                    <div className="label">VLM 분석 페이지</div>
                  </div>
                  <div className="stat-card" style={{ borderLeft: "4px solid var(--gold)" }}>
                    <div className="value">{data.preview.vlm_bom.total_bom_items}</div>
                    <div className="label">BOM 품목</div>
                  </div>
                  <div className="stat-card">
                    <div className="value">{data.preview.vlm_bom.total_pipe_pieces}</div>
                    <div className="label">파이프 피스</div>
                  </div>
                  <div className="stat-card">
                    <div className="value">{data.preview.vlm_bom.total_weld_points}</div>
                    <div className="label">용접 포인트</div>
                  </div>
                  <div className="stat-card">
                    <div className="value">{data.preview.vlm_bom.total_cut_lengths || 0}</div>
                    <div className="label">Cut Lengths</div>
                  </div>
                  <div className="stat-card">
                    <div className="value">{data.preview.vlm_bom.total_components}</div>
                    <div className="label">컴포넌트</div>
                  </div>
                </>
              )}
              {data.preview.valves && !data.preview.vlm_bom && (
                <>
                  <div className="stat-card">
                    <div className="value">{data.preview.valves.total}</div>
                    <div className="label">밸브 총 수</div>
                  </div>
                  <div className="stat-card">
                    <div className="value">{Object.keys(data.preview.valves.by_type).length}</div>
                    <div className="label">밸브 종류</div>
                  </div>
                </>
              )}
              {data.preview.pipe_bom && !data.preview.vlm_bom && (
                <>
                  <div className="stat-card">
                    <div className="value">{data.preview.pipe_bom.total_pages}</div>
                    <div className="label">전체 페이지</div>
                  </div>
                  <div className="stat-card">
                    <div className="value">{data.preview.pipe_bom.total_pieces}</div>
                    <div className="label">파이프 피스</div>
                  </div>
                  <div className="stat-card">
                    <div className="value">{data.preview.pipe_bom.total_welds}</div>
                    <div className="label">용접 항목</div>
                  </div>
                </>
              )}
              {data.preview.dimensions && (
                <div className="stat-card">
                  <div className="value">{Object.keys(data.preview.dimensions.views || {}).length}</div>
                  <div className="label">뷰 분석</div>
                </div>
              )}
            </div>
          )}

          {/* VLM BOM 분석 결과 */}
          {data.preview.vlm_bom && vlmData.length > 0 && (
            <div className="card" style={{ marginBottom: 24 }}>
              <div className="card-header">
                <h3><Eye size={18} style={{ marginRight: 8, verticalAlign: "middle" }} />VLM PIPE BOM 분석 결과</h3>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  {/* 탭 버튼 */}
                  <div style={{ display: "flex", gap: 2 }}>
                    {(["index", "bom", "drawing"] as const).map(tab => (
                      <button
                        key={tab}
                        className={`btn ${vlmTab === tab ? "btn-primary" : "btn-outline"}`}
                        style={{ padding: "4px 10px", fontSize: 12 }}
                        onClick={() => setVlmTab(tab)}
                      >
                        {tab === "index" ? "도면 인덱스" : tab === "bom" ? "BOM 상세" : "도면 분석"}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
              <div className="card-body">

                {/* 인덱스 탭 */}
                {vlmTab === "index" && (
                  <div style={{ overflowX: "auto" }}>
                    <table className="data-table" style={{ fontSize: 12 }}>
                      <thead>
                        <tr>
                          <th>Page</th>
                          <th>Drawing No.</th>
                          <th>Line No.</th>
                          <th>Pipe No.</th>
                          <th>Line Description</th>
                          <th>Pieces</th>
                          <th>Welds</th>
                          <th>BOM</th>
                          <th>Cuts</th>
                          <th style={{ textAlign: "center" }}>Draw</th>
                          <th style={{ textAlign: "center" }}>Table</th>
                        </tr>
                      </thead>
                      <tbody>
                        {vlmData.map((pd: VlmPageData) => {
                          const di = pd.drawing_info || {};
                          return (
                            <tr key={pd.page}>
                              <td style={{ fontWeight: 600 }}>{pd.page}</td>
                              <td>{pd.drawing_number || di.drawing_number || ""}</td>
                              <td>{pd.line_no || di.line_no || ""}</td>
                              <td>{pd.pipe_no || di.pipe_no || ""}</td>
                              <td style={{ maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                {pd.line_description || di.line_description || ""}
                              </td>
                              <td>{(pd.pipe_pieces || []).length || "-"}</td>
                              <td>{(pd.weld_points || []).length || "-"}</td>
                              <td>{(pd.bom_table || []).length || "-"}</td>
                              <td>{(pd.cut_lengths || []).length || "-"}</td>
                              <td style={{ textAlign: "center" }}>
                                {pd.drawing_analysis_ok ?
                                  <span style={{ color: "#16a34a" }}>OK</span> :
                                  <span style={{ color: "#dc2626" }}>-</span>}
                              </td>
                              <td style={{ textAlign: "center" }}>
                                {pd.table_analysis_ok ?
                                  <span style={{ color: "#16a34a" }}>OK</span> :
                                  <span style={{ color: "#dc2626" }}>-</span>}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* BOM 상세 탭 */}
                {vlmTab === "bom" && (
                  <>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
                      <span style={{ fontSize: 13, color: "var(--gray-500)" }}>
                        {vlmData.length}개 페이지, {data.preview.vlm_bom.total_bom_items}개 BOM 품목
                      </span>
                      {totalVlmPages > 1 && (
                        <div style={{ display: "flex", alignItems: "center", gap: 4, marginLeft: "auto" }}>
                          <button className="btn btn-outline" style={{ padding: "4px 8px" }}
                            disabled={vlmPage === 0} onClick={() => setVlmPage(p => p - 1)}>
                            <ChevronLeft size={14} />
                          </button>
                          <span style={{ fontSize: 12, color: "var(--gray-500)", minWidth: 60, textAlign: "center" }}>
                            {vlmPage + 1} / {totalVlmPages}
                          </span>
                          <button className="btn btn-outline" style={{ padding: "4px 8px" }}
                            disabled={vlmPage >= totalVlmPages - 1} onClick={() => setVlmPage(p => p + 1)}>
                            <ChevronRight size={14} />
                          </button>
                        </div>
                      )}
                    </div>

                    {visibleVlm.map((pd: VlmPageData) => (
                      <div key={pd.page} style={{ marginBottom: 16 }}>
                        <div
                          style={{
                            display: "flex", alignItems: "center", gap: 8,
                            padding: "8px 12px", background: "var(--gray-100)", borderRadius: 6,
                            cursor: "pointer"
                          }}
                          onClick={() => setExpandedVlmPage(expandedVlmPage === pd.page ? null : pd.page)}
                        >
                          <span style={{ fontWeight: 700, color: "var(--navy)" }}>Page {pd.page}</span>
                          <span style={{ fontSize: 12, color: "var(--gray-500)" }}>
                            {pd.drawing_number || ""} | Line {pd.line_no || "?"} | {pd.line_description || ""}
                          </span>
                          <span style={{ marginLeft: "auto", fontSize: 12, color: "var(--gray-500)" }}>
                            BOM: {(pd.bom_table || []).length} | Cuts: {(pd.cut_lengths || []).length} | Welds: {(pd.weld_points || []).length}
                          </span>
                          <ChevronRight size={14} style={{
                            transform: expandedVlmPage === pd.page ? "rotate(90deg)" : "none",
                            transition: "transform 0.2s"
                          }} />
                        </div>

                        {expandedVlmPage === pd.page && (
                          <div style={{ padding: "12px 0" }}>
                            {/* BOM Table */}
                            {(pd.bom_table || []).length > 0 && (
                              <div style={{ overflowX: "auto", marginBottom: 12 }}>
                                <h4 style={{ fontSize: 13, color: "var(--navy)", marginBottom: 6 }}>BOM Items</h4>
                                <table className="data-table" style={{ fontSize: 11 }}>
                                  <thead>
                                    <tr>
                                      <th>Code</th><th>Qty</th><th>Size</th>
                                      <th>Description</th><th>Material Spec</th>
                                      <th>Weight</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {(pd.bom_table || []).map((item, i) => (
                                      <tr key={i}>
                                        <td style={{ fontWeight: 600, color: "var(--navy)" }}>
                                          {item.letter_code || item.item_no || ""}
                                        </td>
                                        <td>{item.quantity || ""}</td>
                                        <td>{item.size_inches || ""}</td>
                                        <td style={{ maxWidth: 250 }}>{item.description || ""}</td>
                                        <td style={{ maxWidth: 200, fontSize: 10 }}>{item.material_spec || ""}</td>
                                        <td>{item.weight_kg || ""}</td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            )}

                            {/* Cut Lengths */}
                            {(pd.cut_lengths || []).length > 0 && (
                              <div style={{ marginBottom: 12 }}>
                                <h4 style={{ fontSize: 13, color: "var(--navy)", marginBottom: 6 }}>Cut Lengths</h4>
                                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                                  {(pd.cut_lengths || []).map((cut, i) => (
                                    <span key={i} style={{
                                      padding: "3px 10px", background: "#f0f9ff", border: "1px solid #bae6fd",
                                      borderRadius: 4, fontSize: 12
                                    }}>
                                      {"<"}{cut.cut_no}{">"} {cut.length_mm} mm
                                    </span>
                                  ))}
                                </div>
                              </div>
                            )}

                            {/* Pipe Pieces */}
                            {(pd.pipe_pieces || []).length > 0 && (
                              <div style={{ marginBottom: 8 }}>
                                <h4 style={{ fontSize: 13, color: "var(--navy)", marginBottom: 6 }}>Pipe Pieces</h4>
                                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                                  {(pd.pipe_pieces || []).map((pp: any, i: number) => (
                                    <span key={i} style={{
                                      padding: "3px 10px", background: "#f0fdf4", border: "1px solid #bbf7d0",
                                      borderRadius: 4, fontSize: 12
                                    }}>
                                      {typeof pp === "string" ? pp : pp.id || JSON.stringify(pp)}
                                    </span>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    ))}
                  </>
                )}

                {/* 도면 분석 탭 */}
                {vlmTab === "drawing" && (
                  <>
                    {/* 밸브/피팅 요약 */}
                    <div style={{ display: "flex", gap: 24, marginBottom: 16, flexWrap: "wrap" }}>
                      {data.preview.vlm_bom.valve_summary && Object.keys(data.preview.vlm_bom.valve_summary).length > 0 && (
                        <div>
                          <h4 style={{ fontSize: 14, color: "var(--navy)", marginBottom: 8 }}>밸브 종류</h4>
                          {Object.entries(data.preview.vlm_bom.valve_summary).map(([type, count]) => (
                            <div key={type} style={{ fontSize: 13, display: "flex", justifyContent: "space-between", gap: 16 }}>
                              <span>{type}</span><strong>{count}</strong>
                            </div>
                          ))}
                        </div>
                      )}
                      {data.preview.vlm_bom.fitting_summary && Object.keys(data.preview.vlm_bom.fitting_summary).length > 0 && (
                        <div>
                          <h4 style={{ fontSize: 14, color: "var(--navy)", marginBottom: 8 }}>피팅 종류</h4>
                          {Object.entries(data.preview.vlm_bom.fitting_summary).map(([type, count]) => (
                            <div key={type} style={{ fontSize: 13, display: "flex", justifyContent: "space-between", gap: 16 }}>
                              <span>{type}</span><strong>{count}</strong>
                            </div>
                          ))}
                        </div>
                      )}
                      {data.preview.vlm_bom.unique_line_nos && data.preview.vlm_bom.unique_line_nos.length > 0 && (
                        <div>
                          <h4 style={{ fontSize: 14, color: "var(--navy)", marginBottom: 8 }}>라인 번호 ({data.preview.vlm_bom.unique_line_nos.length}개)</h4>
                          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                            {data.preview.vlm_bom.unique_line_nos.map(ln => (
                              <span key={ln} style={{
                                padding: "2px 8px", background: "#fef3c7", border: "1px solid #fde68a",
                                borderRadius: 4, fontSize: 12
                              }}>{ln}</span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>

                    {/* 컴포넌트 상세 테이블 */}
                    <div style={{ overflowX: "auto" }}>
                      <table className="data-table" style={{ fontSize: 12 }}>
                        <thead>
                          <tr>
                            <th>Page</th><th>Type</th><th>Sub-type</th>
                            <th>Size</th><th>Description</th><th>Qty</th>
                          </tr>
                        </thead>
                        <tbody>
                          {vlmData.flatMap((pd: VlmPageData) =>
                            (pd.components || []).map((c: any, i: number) => (
                              <tr key={`${pd.page}-${i}`}>
                                <td>{pd.page}</td>
                                <td style={{
                                  fontWeight: 600,
                                  color: c.type === "valve" ? "#dc2626" :
                                         c.type === "fitting" ? "#2563eb" : "var(--navy)"
                                }}>{(c.type || "").toUpperCase()}</td>
                                <td>{c.subtype || ""}</td>
                                <td>{c.size || ""}</td>
                                <td>{c.description || ""}</td>
                                <td>{c.quantity || 1}</td>
                              </tr>
                            ))
                          )}
                        </tbody>
                      </table>
                    </div>
                  </>
                )}
              </div>
            </div>
          )}

          {/* 이미지 미리보기 */}
          {data.images.length > 0 && (
            <div className="card" style={{ marginBottom: 24 }}>
              <div className="card-header">
                <h3><Image size={18} style={{ marginRight: 8, verticalAlign: "middle" }} />렌더링 이미지 미리보기</h3>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 13, color: "var(--gray-500)" }}>{data.images.length}개 파일</span>
                  {totalImgPages > 1 && (
                    <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                      <button className="btn btn-outline" style={{ padding: "4px 8px" }}
                        disabled={imgPage === 0} onClick={() => setImgPage(p => p - 1)}>
                        <ChevronLeft size={14} />
                      </button>
                      <span style={{ fontSize: 12, color: "var(--gray-500)", minWidth: 60, textAlign: "center" }}>
                        {imgPage + 1} / {totalImgPages}
                      </span>
                      <button className="btn btn-outline" style={{ padding: "4px 8px" }}
                        disabled={imgPage >= totalImgPages - 1} onClick={() => setImgPage(p => p + 1)}>
                        <ChevronRight size={14} />
                      </button>
                    </div>
                  )}
                </div>
              </div>
              <div className="card-body">
                <div className="image-grid">
                  {visibleImages.map((img) => (
                    <div key={img.name} className="image-card" onClick={() => setModalImage(img.path)}>
                      <img src={img.path} alt={img.name} loading="lazy" />
                      <div className="label">
                        <ZoomIn size={14} style={{ marginRight: 4, verticalAlign: "middle" }} />
                        {img.name}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* 밸브 데이터 미리보기 */}
          {data.preview.valves && (
            <div className="card" style={{ marginBottom: 24 }}>
              <div className="card-header">
                <h3><Wrench size={18} style={{ marginRight: 8, verticalAlign: "middle" }} />밸브 데이터</h3>
              </div>
              <div className="card-body">
                <div style={{ display: "flex", gap: 24, marginBottom: 16, flexWrap: "wrap" }}>
                  <div>
                    <h4 style={{ fontSize: 14, color: "var(--navy)", marginBottom: 8 }}>타입별</h4>
                    {Object.entries(data.preview.valves.by_type).map(([type, count]) => (
                      <div key={type} style={{ fontSize: 13, display: "flex", justifyContent: "space-between", gap: 16 }}>
                        <span>{type}</span><strong>{count}</strong>
                      </div>
                    ))}
                  </div>
                  <div>
                    <h4 style={{ fontSize: 14, color: "var(--navy)", marginBottom: 8 }}>사이즈별</h4>
                    {Object.entries(data.preview.valves.by_size).map(([size, count]) => (
                      <div key={size} style={{ fontSize: 13, display: "flex", justifyContent: "space-between", gap: 16 }}>
                        <span>{size}"</span><strong>{count}</strong>
                      </div>
                    ))}
                  </div>
                </div>
                {data.preview.valves.sample.length > 0 && (
                  <div style={{ overflowX: "auto" }}>
                    <table className="data-table">
                      <thead>
                        <tr><th>TAG</th><th>TYPE</th><th>SIZE</th><th>FLUID</th><th>LOCATION</th><th>SHEET</th></tr>
                      </thead>
                      <tbody>
                        {data.preview.valves.sample.map((v: any) => (
                          <tr key={v.tag}>
                            <td>{v.tag}</td><td>{v.valve_type}</td><td>{v.size}"</td>
                            <td>{v.fluid}</td><td>{v.location}</td><td>{v.sheet}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* BOM 전체 데이터 테이블 (기존) */}
          {data.preview.pipe_bom && bomData.length > 0 && !data.preview.vlm_bom && (
            <div className="card" style={{ marginBottom: 24 }}>
              <div className="card-header">
                <h3><Package size={18} style={{ marginRight: 8, verticalAlign: "middle" }} />PIPE BOM 데이터</h3>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 13, color: "var(--gray-500)" }}>{bomData.length}개 페이지</span>
                  {totalBomPages > 1 && (
                    <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                      <button className="btn btn-outline" style={{ padding: "4px 8px" }}
                        disabled={bomPage === 0} onClick={() => setBomPage(p => p - 1)}>
                        <ChevronLeft size={14} />
                      </button>
                      <span style={{ fontSize: 12, color: "var(--gray-500)", minWidth: 60, textAlign: "center" }}>
                        {bomPage + 1} / {totalBomPages}
                      </span>
                      <button className="btn btn-outline" style={{ padding: "4px 8px" }}
                        disabled={bomPage >= totalBomPages - 1} onClick={() => setBomPage(p => p + 1)}>
                        <ChevronRight size={14} />
                      </button>
                    </div>
                  )}
                </div>
              </div>
              <div className="card-body">
                <div style={{ overflowX: "auto" }}>
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Page</th><th>Pipe Pieces</th><th>피스 수</th>
                        <th>Welds</th><th>용접 항목</th><th>치수 (mm)</th><th>Loose</th>
                      </tr>
                    </thead>
                    <tbody>
                      {visibleBom.map((pd: BomPage) => (
                        <tr key={pd.page} style={pd.is_cover ? { opacity: 0.5 } : undefined}>
                          <td style={{ fontWeight: 600 }}>{pd.page}</td>
                          <td style={{ maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {(pd.pipe_pieces || []).join(", ") || "-"}
                          </td>
                          <td>{(pd.pipe_pieces || []).length || "-"}</td>
                          <td>{pd.weld_count || "-"}</td>
                          <td style={{ maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {(pd.weld_items || []).join(", ") || "-"}
                          </td>
                          <td style={{ maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {(pd.dimensions_mm || []).join(", ") || "-"}
                          </td>
                          <td>{pd.has_loose ? "Yes" : "-"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* 다운로드 */}
          <div className="card">
            <div className="card-header">
              <h3><Download size={18} style={{ marginRight: 8, verticalAlign: "middle" }} />다운로드</h3>
              <a href={`${API}/download/${sessionId}`} className="btn btn-gold" style={{ fontSize: 13 }}>
                <Download size={14} /> 전체 ZIP 다운로드
              </a>
            </div>
            <div className="card-body">
              <div className="download-list">
                {data.excel_files.map((f) => (
                  <div key={f.name} className="download-item">
                    <div className="file-info">
                      <div className="file-icon excel"><FileSpreadsheet size={18} /></div>
                      <div>
                        <div style={{ fontWeight: 500 }}>{f.name}</div>
                        <div style={{ fontSize: 12, color: "var(--gray-500)" }}>{(f.size / 1024).toFixed(0)} KB</div>
                      </div>
                    </div>
                    <a href={`${API}/download/${sessionId}/${f.name}`} className="btn btn-outline" style={{ padding: "4px 12px", fontSize: 13 }}>
                      <Download size={14} /> 다운로드
                    </a>
                  </div>
                ))}
                {data.images.length > 0 && (
                  <div className="download-item">
                    <div className="file-info">
                      <div className="file-icon image"><Image size={18} /></div>
                      <div>
                        <div style={{ fontWeight: 500 }}>이미지 파일 ({data.images.length}개)</div>
                        <div style={{ fontSize: 12, color: "var(--gray-500)" }}>
                          {(data.images.reduce((sum, f) => sum + f.size, 0) / 1024 / 1024).toFixed(1)} MB
                        </div>
                      </div>
                    </div>
                    <a href={`${API}/download/${sessionId}`} className="btn btn-outline" style={{ padding: "4px 12px", fontSize: 13 }}>
                      <Download size={14} /> ZIP 다운로드
                    </a>
                  </div>
                )}
              </div>
            </div>
          </div>
        </>
      )}

      {/* 이미지 모달 */}
      {modalImage && (
        <div className="image-modal-overlay" onClick={() => setModalImage(null)}>
          <div className="image-modal-close" onClick={() => setModalImage(null)}>
            <X size={20} />
          </div>
          <img src={modalImage} alt="Preview" onClick={(e) => e.stopPropagation()} />
        </div>
      )}
    </div>
  );
}
