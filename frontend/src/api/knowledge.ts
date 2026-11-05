import { apiFetch, errorMessage, jsonRequest, requestJson } from "./http";

export interface KnowledgeBase {
  id: string; name: string; description: string; enabled: boolean; version: number;
}
export interface KnowledgeDocument {
  id: string; title: string; status: string; knowledge_base_id: string;
}
export interface DocumentVersion {
  id: string; document_id: string; version_number: number;
  original_filename: string; size_bytes: number; status: string;
  error_message: string | null; created_at: string;
}
export interface EmbeddingProfile {
  id: string; provider_id: string; base_url: string; model_name: string;
  model_revision: string; dimensions: number; send_dimensions: boolean;
}
export interface ChunkSet {
  id: string; version_id: string; chunk_size: number; chunk_overlap: number;
}
export interface Chunk {
  id: string; chunk_index: number; text: string; start_char: number; end_char: number;
}
export interface Publication {
  document_id: string; chunk_set_id: string; profile_id: string; updated_at: string;
}
export interface IngestionJob {
  id: string; document_id: string; version_id: string; profile_id: string;
  status: string; stage: string; chunk_set_id: string | null;
  chunk_size: number; chunk_overlap: number; rebuild: boolean;
  cancel_requested: boolean; error_message: string | null; created_at: string;
}
export interface RetrievalHit {
  citation: string; chunk_id: string; chunk_set_id: string; profile_id: string;
  knowledge_base_id: string; document_id: string; version_id: string;
  title: string; filename: string; version_number: number; chunk_index: number;
  start_char: number; end_char: number; score: number; text: string;
}
export interface RetrievalResult {
  request_id: string; hits: RetrievalHit[]; latency_ms: number;
  searched_profiles: string[];
  answer?: string; status?: string; cited_ids?: string[];
}
export interface RagStatus {
  qdrant: string; documents: number; knowledge_bases: number;
  publications: number; active_jobs: number;
}
export interface KnowledgeBinding {
  knowledge_base_id: string; knowledge_base_name: string; enabled: boolean;
}
export interface QueryAudit {
  id: string; operation: string; status: string; agent_id: string | null;
  latency_ms: number; hit_count: number; created_at: string;
}
export interface QueryHistoryEntry {
  request_id: string;
  query: string;
  response: RetrievalResult | null;
  operation: "search" | "answer";
  status: string;
  agent_id: string | null;
  latency_ms: number;
  hit_count: number;
  created_at: string;
}
export interface QueryHistoryPage {
  items: QueryHistoryEntry[];
  total: number;
}

const root = "/api";
export const knowledgeApi = {
  bases: () => requestJson<KnowledgeBase[]>(`${root}/knowledge-bases`),
  createBase: (body: unknown) => requestJson<KnowledgeBase>(`${root}/knowledge-bases`, jsonRequest("POST", body)),
  updateBase: (id: string, body: unknown) => requestJson<KnowledgeBase>(`${root}/knowledge-bases/${id}`, jsonRequest("PUT", body)),
  documents: (id: string) => requestJson<KnowledgeDocument[]>(`${root}/knowledge-bases/${id}/documents`),
  createDocument: (id: string, title: string) => requestJson<KnowledgeDocument>(`${root}/knowledge-bases/${id}/documents`, jsonRequest("POST", { title })),
  updateDocument: (id: string, body: unknown) => requestJson(`${root}/knowledge-documents/${id}`, jsonRequest("PATCH", body)),
  versions: (id: string) => requestJson<DocumentVersion[]>(`${root}/knowledge-documents/${id}/versions`),
  async upload(id: string, file: File) {
    const data = new FormData();
    data.append("file", file);
    return requestJson<DocumentVersion>(`${root}/knowledge-documents/${id}/versions`, { method: "POST", body: data });
  },
  profiles: () => requestJson<EmbeddingProfile[]>(`${root}/knowledge-embedding-profiles?limit=100`),
  createProfile: (body: unknown) => requestJson<EmbeddingProfile>(`${root}/knowledge-embedding-profiles`, jsonRequest("POST", body)),
  chunkSets: (document: string, version: string) => requestJson<ChunkSet[]>(`${root}/knowledge-documents/${document}/versions/${version}/chunk-sets?limit=100`),
  chunks: (document: string, version: string, set: string, offset = 0) => requestJson<{ total: number; items: Chunk[] }>(`${root}/knowledge-documents/${document}/versions/${version}/chunk-sets/${set}/chunks?limit=10&offset=${offset}`),
  publications: (id: string) => requestJson<Publication[]>(`${root}/knowledge/publications?knowledge_base_id=${id}`),
  publish: (id: string, body: unknown) => requestJson<Publication>(`${root}/knowledge-documents/${id}/publication`, jsonRequest("PUT", body)),
  async unpublish(id: string) {
    const response = await apiFetch(`${root}/knowledge-documents/${id}/publication`, { method: "DELETE" });
    if (!response.ok) throw new Error(await errorMessage(response));
  },
  ingest: (document: string, version: string, body: unknown) => requestJson<IngestionJob>(`${root}/knowledge-documents/${document}/versions/${version}/ingest`, jsonRequest("POST", body)),
  jobs: () => requestJson<IngestionJob[]>(`${root}/knowledge/jobs?limit=100`),
  cancel: (id: string) => requestJson(`${root}/knowledge/jobs/${id}/cancel`, { method: "POST" }),
  search: (body: unknown, answer: boolean) => requestJson<RetrievalResult>(`${root}/knowledge/${answer ? "answer" : "search"}`, jsonRequest("POST", body)),
  status: () => requestJson<RagStatus>(`${root}/knowledge/status`),
  bindings: (id: string) => requestJson<KnowledgeBinding[]>(`${root}/agents/${id}/knowledge-bases`),
  bind: (agent: string, kb: string) => requestJson(`${root}/agents/${agent}/knowledge-bases`, jsonRequest("POST", { knowledge_base_id: kb })),
  toggleBinding: (agent: string, kb: string, enabled: boolean) => requestJson(`${root}/agents/${agent}/knowledge-bases/${kb}`, jsonRequest("PATCH", { enabled })),
  audits: () => requestJson<QueryAudit[]>(`${root}/knowledge/audits?limit=100`),
  history: (limit = 10, offset = 0) => requestJson<QueryHistoryPage>(
    `${root}/knowledge/history?limit=${limit}&offset=${offset}`,
  ),
};
