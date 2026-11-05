import {
  Alert, Button, Drawer, Empty, Form, Input, InputNumber, Modal, Pagination,
  Popconfirm, Segmented, Select, Space, Spin, Switch, Table, Tabs, Tag,
  Tooltip, Typography, Upload, message,
} from "antd";
import {
  Archive, ArrowRight, BookOpen, CheckCircle2, Database, FileText, Layers,
  LoaderCircle, Plus, RefreshCw, Search, Send, Settings2, ShieldCheck, UploadCloud,
  X, Zap,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { listAgents, type Agent } from "../api/agents";
import { listProviders, type Provider } from "../api/providers";
import {
  knowledgeApi as api, type Chunk, type ChunkSet, type DocumentVersion,
  type EmbeddingProfile, type IngestionJob, type KnowledgeBase,
  type KnowledgeBinding, type KnowledgeDocument, type Publication,
  type QueryAudit, type QueryHistoryEntry, type QueryHistoryPage, type RagStatus,
  type RetrievalResult,
} from "../api/knowledge";

const { Text, Title } = Typography;
const errorText = (e: unknown) => e instanceof Error ? e.message : "操作失败";
const activeJob = (job: IngestionJob) => ["queued", "running"].includes(job.status);
const workspaceTabs = [
  ["documents", "文档"], ["query", "检索与问答"], ["history", "查询历史"],
  ["profiles", "向量配置"], ["access", "Agent 授权"], ["jobs", "处理任务"],
  ["audits", "查询审计"],
] as const;
const labels: Record<string, string> = {
  queued: "等待处理", running: "处理中", completed: "完成", failed: "失败",
  cancelled: "已取消", parsing: "解析", chunking: "切块", embedding: "向量化",
  indexing: "索引", publishing: "发布", uploaded: "待解析", parsed: "已解析",
  parse_failed: "解析失败", answered: "已回答", invalid_citations: "引用无效",
  insufficient_evidence: "证据不足",
};
const statusTag = (status: string) => <Tag color={
  ["completed", "answered", "parsed"].includes(status) ? "success"
    : ["failed", "parse_failed", "invalid_citations"].includes(status) ? "error"
    : ["running", "queued"].includes(status) ? "processing" : "default"
}>{labels[status] ?? status}</Tag>;

export default function KnowledgePage() {
  const [tab, setTab] = useState("documents");
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const [baseId, setBaseId] = useState<string>();
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [publications, setPublications] = useState<Publication[]>([]);
  const [profiles, setProfiles] = useState<EmbeddingProfile[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [jobs, setJobs] = useState<IngestionJob[]>([]);
  const [audits, setAudits] = useState<QueryAudit[]>([]);
  const [queryHistory, setQueryHistory] = useState<QueryHistoryEntry[]>([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyPage, setHistoryPage] = useState(1);
  const [status, setStatus] = useState<RagStatus>();
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [baseModal, setBaseModal] = useState<"create" | "edit" | null>(null);
  const [profileModal, setProfileModal] = useState(false);
  const [uploadModal, setUploadModal] = useState(false);
  const [file, setFile] = useState<File>();
  const [selectedDocument, setSelectedDocument] = useState<KnowledgeDocument>();
  const [versions, setVersions] = useState<DocumentVersion[]>([]);
  const [versionId, setVersionId] = useState<string>();
  const [sets, setSets] = useState<ChunkSet[]>([]);
  const [setId, setSetId] = useState<string>();
  const [chunkPage, setChunkPage] = useState({ total: 0, items: [] as Chunk[] });
  const [chunkOffset, setChunkOffset] = useState(0);
  const [profileId, setProfileId] = useState<string>();
  const [bindingAgent, setBindingAgent] = useState<string>();
  const [bindings, setBindings] = useState<KnowledgeBinding[]>([]);
  const [mode, setMode] = useState("search");
  const [result, setResult] = useState<RetrievalResult>();
  const [searching, setSearching] = useState(false);
  const [baseForm] = Form.useForm();
  const [profileForm] = Form.useForm();
  const [uploadForm] = Form.useForm();
  const [ingestForm] = Form.useForm();
  const [queryForm] = Form.useForm();
  const providerId = Form.useWatch("provider_id", profileForm);
  const generationProviderId = Form.useWatch("provider_id", queryForm);
  const queryAgentId = Form.useWatch("agent_id", queryForm);
  // 每次切换资源递增序号，迟到的 HTTP 响应不能覆盖新选择。
  const documentEpoch = useRef(0);
  const baseEpoch = useRef(0);
  const versionEpoch = useRef(0);
  const chunkEpoch = useRef(0);
  const bindingEpoch = useRef(0);
  const queryEpoch = useRef(0);
  const restoringHistory = useRef(false);
  const currentBase = bases.find(item => item.id === baseId);
  const profileOptions = profiles.map(item => ({
    value: item.id, label: `${item.model_name} · ${item.dimensions}d · ${item.id.slice(0, 6)}`,
  }));

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [nextBases, nextProfiles, nextProviders, nextAgents, nextJobs, nextStatus, nextAudits, nextHistory] = await Promise.all([
        api.bases(), api.profiles(), listProviders(), listAgents(), api.jobs(), api.status(), api.audits(), api.history(),
      ]);
      setBases(nextBases); setProfiles(nextProfiles); setProviders(nextProviders);
      setAgents(nextAgents); setJobs(nextJobs); setStatus(nextStatus); setAudits(nextAudits);
      setQueryHistory(nextHistory.items); setHistoryTotal(nextHistory.total); setHistoryPage(1);
      setBaseId(current => current && nextBases.some(k => k.id === current) ? current : nextBases[0]?.id);
      setProfileId(current => current ?? nextProfiles[0]?.id);
      setError("");
    } catch (e) { setError(errorText(e)); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const refreshDocuments = useCallback(async () => {
    const epoch = ++baseEpoch.current;
    if (!baseId) { setDocuments([]); setPublications([]); return; }
    try {
      const [docs, published] = await Promise.all([api.documents(baseId), api.publications(baseId)]);
      if (epoch === baseEpoch.current) { setDocuments(docs); setPublications(published); }
    } catch (e) { if (epoch === baseEpoch.current) setError(errorText(e)); }
  }, [baseId]);
  useEffect(() => {
    setDocuments([]); setPublications([]); setSelectedDocument(undefined);
    documentEpoch.current++;
    void refreshDocuments();
  }, [refreshDocuments]);

  useEffect(() => {
    let disposed = false;
    // 任务阶段异步刷新；清理定时器，离开页面后不继续请求。
    const timer = window.setInterval(() => {
      if (document.hidden) return;
      void api.jobs().then(next => {
        if (disposed) return;
        const wasActive = jobs.some(activeJob);
        setJobs(next);
        if (wasActive && !next.some(activeJob)) {
          void refreshDocuments(); void refresh();
        }
      }).catch(e => { if (!disposed) setError(errorText(e)); });
    }, 4000);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [jobs, refresh, refreshDocuments]);

  useEffect(() => {
    const epoch = ++versionEpoch.current;
    setSets([]); setSetId(undefined); setChunkPage({ total: 0, items: [] });
    if (!selectedDocument || !versionId) return;
    void api.chunkSets(selectedDocument.id, versionId).then(items => {
      if (epoch !== versionEpoch.current) return;
      setSets(items); setSetId(items[0]?.id);
    }).catch(e => { if (epoch === versionEpoch.current) setError(errorText(e)); });
  }, [selectedDocument, versionId]);

  useEffect(() => {
    const epoch = ++chunkEpoch.current;
    setChunkOffset(0); setChunkPage({ total: 0, items: [] });
    if (!selectedDocument || !versionId || !setId) return;
    void api.chunks(selectedDocument.id, versionId, setId).then(page => {
      if (epoch === chunkEpoch.current) setChunkPage(page);
    }).catch(e => { if (epoch === chunkEpoch.current) setError(errorText(e)); });
  }, [selectedDocument, versionId, setId]);

  useEffect(() => {
    if (restoringHistory.current) {
      restoringHistory.current = false;
      return;
    }
    queryEpoch.current++;
    setResult(undefined);
    setSearching(false);
  }, [baseId, queryAgentId, mode]);

  async function action(work: () => Promise<unknown>, success: string) {
    setBusy(true); setError("");
    try { await work(); void message.success(success); await refreshDocuments(); await refresh(); }
    catch (e) { setError(errorText(e)); void message.error(errorText(e)); }
    finally { setBusy(false); }
  }

  async function openDocument(doc: KnowledgeDocument) {
    const epoch = ++documentEpoch.current;
    setSelectedDocument(doc); setVersions([]); setVersionId(undefined);
    ingestForm.setFieldsValue({ chunk_size: 800, chunk_overlap: 100, rebuild: false });
    try {
      const items = await api.versions(doc.id);
      if (epoch !== documentEpoch.current) return;
      setVersions(items); setVersionId(items[0]?.id);
    } catch (e) { if (epoch === documentEpoch.current) setError(errorText(e)); }
  }

  async function submitUpload(values: { title: string }) {
    if (!baseId || !file) { void message.warning("请选择文档文件"); return; }
    await action(async () => {
      const doc = selectedDocument ?? await api.createDocument(baseId, values.title);
      // 上传失败后保留逻辑文档，重试时不会再创建一个同名空文档。
      setSelectedDocument(doc);
      await api.upload(doc.id, file);
      setUploadModal(false); setFile(undefined); uploadForm.resetFields();
      await openDocument(doc);
    }, "源文件已保存");
  }

  async function loadBindings(id: string) {
    const epoch = ++bindingEpoch.current;
    setBindingAgent(id); setBindings([]);
    try {
      const next = await api.bindings(id);
      if (epoch === bindingEpoch.current) setBindings(next);
    } catch (e) { if (epoch === bindingEpoch.current) setError(errorText(e)); }
  }

  async function submitQuery(values: Record<string, unknown>) {
    const epoch = ++queryEpoch.current;
    setSearching(true); setError(""); setResult(undefined);
    try {
      const { provider_id, model_id, agent_id, ...rest } = values;
      const payload = {
        ...rest,
        ...(agent_id ? { agent_id, knowledge_base_ids: [] } : { knowledge_base_ids: baseId ? [baseId] : [] }),
        ...(mode === "answer" && !agent_id ? { provider_id, model_id } : {}),
      };
      const response = await api.search(payload, mode === "answer");
      if (epoch === queryEpoch.current) {
        setResult(response);
        void api.history().then(page => {
          setQueryHistory(page.items); setHistoryTotal(page.total); setHistoryPage(1);
        }).catch(e => setError(errorText(e)));
      }
    } catch (e) { if (epoch === queryEpoch.current) setError(errorText(e)); }
    finally { if (epoch === queryEpoch.current) setSearching(false); }
  }

  const documentColumns = [
    { title: "文档", key: "title", render: (_: unknown, doc: KnowledgeDocument) => (
      <button className="document-link" onClick={() => void openDocument(doc)}>
        <span className="file-mark"><FileText size={19} /></span>
        <span><strong>{doc.title}</strong><small>{doc.id.slice(0, 8)}</small></span>
      </button>
    ) },
    { title: "发布状态", key: "publication", render: (_: unknown, doc: KnowledgeDocument) => (
      doc.status === "archived" ? <Tag>已归档</Tag>
        : publications.some(p => p.document_id === doc.id) ? <Tag color="success">已发布</Tag> : <Tag>未发布</Tag>
    ) },
    { title: "当前任务", key: "job", render: (_: unknown, doc: KnowledgeDocument) => {
      const job = jobs.find(j => j.document_id === doc.id);
      return job ? <Space>{statusTag(job.status)}<Text type="secondary">{labels[job.stage] ?? job.stage}</Text></Space> : <Text type="secondary">—</Text>;
    } },
    { title: "操作", key: "actions", render: (_: unknown, doc: KnowledgeDocument) => (
      <Space>
        <Button size="small" onClick={() => void openDocument(doc)}>管理</Button>
        <Tooltip title={doc.status === "archived" ? "恢复文档" : "归档文档"}>
          <Button size="small" type="text" icon={<Archive size={16} />} disabled={busy}
            onClick={() => void action(() => api.updateDocument(doc.id, { archived: doc.status !== "archived" }), "文档状态已更新")} />
        </Tooltip>
      </Space>
    ) },
  ];

  function restoreHistory(entry: QueryHistoryEntry) {
    if (!entry.response) return;
    queryEpoch.current++;
    restoringHistory.current = entry.operation !== mode;
    queryForm.setFieldValue("query", entry.query);
    setMode(entry.operation);
    setResult(entry.response);
    setSearching(false);
    setTab("query");
  }

  async function loadHistoryPage(page: number) {
    try {
      const next: QueryHistoryPage = await api.history(10, (page - 1) * 10);
      setQueryHistory(next.items);
      setHistoryTotal(next.total);
      setHistoryPage(page);
    } catch (e) {
      setError(errorText(e));
    }
  }

  return (
    <div className="knowledge-page">
      <div className="knowledge-toolbar">
        <div className="knowledge-heading"><span className="workspace-symbol"><BookOpen size={24} /></span>
          <div><Title level={3}>知识工作台</Title><Text type="secondary">文档、检索与引用问答</Text></div>
        </div>
        <Space>
          <Tooltip title="刷新"><Button aria-label="刷新知识工作台" icon={<RefreshCw size={16} />} loading={loading} onClick={() => void refresh().then(refreshDocuments)} /></Tooltip>
          <Button type="primary" icon={<Plus size={16} />} onClick={() => { baseForm.resetFields(); setBaseModal("create"); }}>新建知识库</Button>
        </Space>
      </div>
      {error && <Alert type="error" showIcon closable title={error} onClose={() => setError("")} />}
      <section className="knowledge-metrics">
        {[
          { label: "知识库", value: status?.knowledge_bases ?? "—", icon: <Database size={18} /> },
          { label: "文档", value: status?.documents ?? "—", icon: <FileText size={18} /> },
          { label: "已发布", value: status?.publications ?? "—", icon: <CheckCircle2 size={18} /> },
          { label: "处理中", value: status?.active_jobs ?? "—", icon: <LoaderCircle size={18} /> },
        ].map(item => <div className="knowledge-metric" key={item.label}>{item.icon}<span>{item.label}</span><strong>{item.value}</strong></div>)}
        <div className="knowledge-connection"><span className={`status-dot ${status?.qdrant === "ok" ? "ready" : ""}`} />Qdrant {status?.qdrant === "ok" ? "在线" : "不可用"}</div>
      </section>
      <div className="knowledge-workspace">
        <aside className="knowledge-sidebar">
          <div className="knowledge-sidebar-heading"><Text type="secondary">知识库</Text><Tag>{bases.length}</Tag></div>
          {bases.map(base => <button key={base.id} className={`knowledge-base-item ${base.id === baseId ? "selected" : ""}`} onClick={() => setBaseId(base.id)}>
            <Database size={17} /><span><strong>{base.name}</strong><small>{base.enabled ? "已启用" : "已停用"}</small></span><ArrowRight size={14} />
          </button>)}
          {!bases.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无知识库" />}
        </aside>
        <main className="knowledge-main">
          <div className="knowledge-base-heading">
            <div><Title level={4}>{currentBase?.name ?? "知识资源"}</Title><Text type="secondary">{currentBase?.description || "—"}</Text></div>
            {currentBase && <Space>
              <Switch checked={currentBase.enabled} checkedChildren="启用" unCheckedChildren="停用" loading={busy}
                onChange={enabled => void action(() => api.updateBase(currentBase.id, { enabled, expected_version: currentBase.version }), "知识库状态已更新")} />
              <Tooltip title="编辑知识库"><Button aria-label="编辑知识库" icon={<Settings2 size={16} />} onClick={() => { baseForm.setFieldsValue(currentBase); setBaseModal("edit"); }} /></Tooltip>
            </Space>}
          </div>
          <Tabs activeKey={tab} onChange={setTab} renderTabBar={props => (
            // 原生滚动不与组件库的 transform 分页竞争，窄屏也能可靠点击全部入口。
            <div className="knowledge-tabbar" role="tablist" aria-label="知识工作区">
              {workspaceTabs.map(([key, label], index) => (
                <button key={key} type="button" role="tab"
                  id={`${props.id}-tab-${key}`} aria-controls={`${props.id}-panel-${key}`}
                  aria-selected={tab === key} tabIndex={tab === key ? 0 : -1}
                  onClick={event => props.onTabClick(key, event)}
                  onKeyDown={event => {
                    const direction = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
                    if (!direction && !["Home", "End"].includes(event.key)) return;
                    event.preventDefault();
                    const target = event.key === "Home" ? 0 : event.key === "End" ? workspaceTabs.length - 1
                      : (index + direction + workspaceTabs.length) % workspaceTabs.length;
                    props.onTabClick(workspaceTabs[target][0], event);
                    const button = event.currentTarget.parentElement?.querySelectorAll("button")[target];
                    button?.focus(); button?.scrollIntoView({ block: "nearest", inline: "nearest" });
                  }}>
                  {label}{key === "jobs" && jobs.some(activeJob) && <Tag color="processing">{jobs.filter(activeJob).length}</Tag>}
                </button>
              ))}
            </div>
          )} items={[
            { key: "documents", label: "文档", children: <div>
              <div className="table-toolbar"><Text type="secondary">{documents.length} 份文档</Text>
                <Button icon={<UploadCloud size={16} />} disabled={!baseId} onClick={() => { setSelectedDocument(undefined); uploadForm.resetFields(); setFile(undefined); setUploadModal(true); }}>上传文档</Button>
              </div>
              <Table rowKey="id" columns={documentColumns} dataSource={documents} loading={loading} pagination={{ pageSize: 10 }} scroll={{ x: 640 }}
                locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无文档" /> }} />
            </div> },
            { key: "query", label: "检索与问答", children: <div className="retrieval-lab">
              <Form form={queryForm} layout="vertical" onFinish={submitQuery} initialValues={{ top_k: 5, min_score: 0 }}>
                <div className="table-toolbar"><Segmented value={mode} options={[{ label: "检索", value: "search" }, { label: "引用问答", value: "answer" }]} onChange={value => { setMode(value); setResult(undefined); }} /></div>
                <div className="rag-form-grid">
                  <Form.Item name="agent_id" label="Agent 范围"><Select allowClear placeholder="当前知识库" options={agents.filter(a => a.status === "active").map(a => ({ value: a.id, label: a.name }))} /></Form.Item>
                  <Form.Item name="profile_id" label="Embedding 配置"><Select allowClear placeholder="全部已发布配置" options={profileOptions} /></Form.Item>
                  <Form.Item name="top_k" label="Top K"><InputNumber min={1} max={20} /></Form.Item>
                  <Form.Item name="min_score" label="最低相似度"><InputNumber min={-1} max={1} step={0.05} /></Form.Item>
                </div>
                {mode === "answer" && !queryAgentId && <div className="rag-form-grid two">
                  <Form.Item name="provider_id" label="回答模型服务" rules={[{ required: true }]}><Select options={providers.filter(p => p.enabled).map(p => ({ value: p.id, label: p.name }))} onChange={() => queryForm.setFieldValue("model_id", undefined)} /></Form.Item>
                  <Form.Item name="model_id" label="回答模型" rules={[{ required: true }]}><Select options={providers.find(p => p.id === generationProviderId)?.models.filter(m => m.enabled).map(m => ({ value: m.id, label: m.model_name }))} /></Form.Item>
                </div>}
                <Form.Item name="query" rules={[{ required: true, whitespace: true, message: "请输入问题" }]}><Input.TextArea rows={3} maxLength={4000} placeholder="输入要查找的问题" /></Form.Item>
                <Button type="primary" htmlType="submit" loading={searching} icon={mode === "search" ? <Search size={16} /> : <Send size={16} />} disabled={!baseId && !queryAgentId}>{mode === "search" ? "检索" : "生成回答"}</Button>
              </Form>
              {searching && <div className="retrieval-loading"><Spin /></div>}
              {result && <section className="retrieval-results">
                <div className="table-toolbar"><Text strong>{result.hits.length} 条证据</Text><Space>{result.status && statusTag(result.status)}<Tag>{result.latency_ms} ms</Tag></Space></div>
                {result.answer && <div className="rag-answer markdown-content"><ReactMarkdown remarkPlugins={[remarkGfm]}>{result.answer}</ReactMarkdown></div>}
                {!result.hits.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的已发布证据" />}
                {result.hits.map(hit => <article className="evidence-item" key={hit.chunk_id}>
                  <div className="evidence-heading"><Space><Tag color="cyan">{hit.citation}</Tag><Text strong>{hit.title}</Text></Space><Tag>{hit.score.toFixed(3)}</Tag></div>
                  <Text type="secondary">{hit.filename} · v{hit.version_number} · 片段 {hit.chunk_index + 1} · 字符 {hit.start_char}–{hit.end_char}</Text>
                  <p>{hit.text}</p><Text copyable={{ text: hit.chunk_id }} code>{hit.chunk_id}</Text>
                </article>)}
              </section>}
            </div> },
            { key: "history", label: "查询历史", children: <Table
              rowKey="request_id"
              dataSource={queryHistory}
              scroll={{ x: 900 }}
              pagination={{
                current: historyPage, pageSize: 10, total: historyTotal,
                showSizeChanger: false, onChange: page => void loadHistoryPage(page),
              }}
              columns={[
                { title: "提问", dataIndex: "query", width: 360, ellipsis: true },
                { title: "类型", render: (_: unknown, item: QueryHistoryEntry) => item.operation === "answer" ? "引用问答" : "检索" },
                { title: "状态", render: (_: unknown, item: QueryHistoryEntry) => statusTag(item.status) },
                { title: "证据", dataIndex: "hit_count" },
                { title: "耗时 ms", dataIndex: "latency_ms" },
                { title: "时间", render: (_: unknown, item: QueryHistoryEntry) => new Date(item.created_at).toLocaleString() },
                { title: "操作", render: (_: unknown, item: QueryHistoryEntry) => (
                  <Button size="small" disabled={!item.response} onClick={() => restoreHistory(item)}>查看记录</Button>
                ) },
              ]}
              locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无查询记录" /> }}
            /> },
            { key: "profiles", label: "向量配置", children: <div>
              <div className="table-toolbar"><Text type="secondary">{profiles.length} 个配置</Text><Button icon={<Plus size={16} />} onClick={() => { profileForm.resetFields(); setProfileModal(true); }}>新建配置</Button></div>
              <Table rowKey="id" dataSource={profiles} scroll={{ x: 650 }} pagination={{ pageSize: 8 }} columns={[
                { title: "模型", dataIndex: "model_name" }, { title: "维度", dataIndex: "dimensions" },
                { title: "版本", dataIndex: "model_revision" },
                { title: "服务", render: (_: unknown, p: EmbeddingProfile) => providers.find(v => v.id === p.provider_id)?.name ?? p.provider_id.slice(0, 8) },
                { title: "ID", render: (_: unknown, p: EmbeddingProfile) => <Text copyable={{ text: p.id }} code>{p.id.slice(0, 8)}</Text> },
              ]} />
            </div> },
            { key: "access", label: "Agent 授权", children: <div>
              <div className="table-toolbar"><Select placeholder="选择 Agent" value={bindingAgent} style={{ width: 260, maxWidth: "100%" }} options={agents.map(a => ({ value: a.id, label: a.name }))} onChange={id => void loadBindings(id)} /><ShieldCheck size={18} /></div>
              {bindingAgent ? <Table rowKey="id" dataSource={bases} pagination={false} columns={[
                { title: "知识库", dataIndex: "name" },
                { title: "知识库状态", render: (_: unknown, base: KnowledgeBase) => <Tag>{base.enabled ? "启用" : "停用"}</Tag> },
                { title: "访问授权", render: (_: unknown, base: KnowledgeBase) => <Switch loading={busy} checked={bindings.some(b => b.knowledge_base_id === base.id && b.enabled)} onChange={enabled => void action(async () => {
                  if (bindings.some(b => b.knowledge_base_id === base.id)) await api.toggleBinding(bindingAgent, base.id, enabled);
                  else await api.bind(bindingAgent, base.id);
                  await loadBindings(bindingAgent);
                }, "授权已更新")} /> },
              ]} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请选择 Agent" />}
            </div> },
            { key: "jobs", label: <Space>处理任务{jobs.some(activeJob) && <Tag color="processing">{jobs.filter(activeJob).length}</Tag>}</Space>, children: <Table rowKey="id" dataSource={jobs} scroll={{ x: 760 }} pagination={{ pageSize: 10 }} columns={[
              { title: "任务", render: (_: unknown, j: IngestionJob) => <Text copyable={{ text: j.id }} code>{j.id.slice(0, 8)}</Text> },
              { title: "状态", render: (_: unknown, j: IngestionJob) => statusTag(j.status) },
              { title: "阶段", render: (_: unknown, j: IngestionJob) => labels[j.stage] ?? j.stage },
              { title: "时间", render: (_: unknown, j: IngestionJob) => new Date(j.created_at).toLocaleString() },
              { title: "错误", dataIndex: "error_message", ellipsis: true },
              { title: "操作", render: (_: unknown, j: IngestionJob) => activeJob(j) ? <Button size="small" icon={<X size={14} />} disabled={j.cancel_requested || busy} onClick={() => void action(() => api.cancel(j.id), "取消请求已提交")}>{j.cancel_requested ? "取消中" : "取消"}</Button> : ["failed", "cancelled"].includes(j.status) ? <Button size="small" icon={<RefreshCw size={14} />} disabled={busy} onClick={() => void action(() => api.ingest(j.document_id, j.version_id, { profile_id: j.profile_id, chunk_size: j.chunk_size, chunk_overlap: j.chunk_overlap, rebuild: j.rebuild }), "重试任务已提交")}>重试</Button> : null },
            ]} /> },
            { key: "audits", label: "查询审计", children: <Table rowKey="id" dataSource={audits} scroll={{ x: 650 }} pagination={{ pageSize: 10 }} columns={[
              { title: "请求", render: (_: unknown, a: QueryAudit) => <Text copyable={{ text: a.id }} code>{a.id.slice(0, 8)}</Text> },
              { title: "操作", dataIndex: "operation" }, { title: "状态", dataIndex: "status" },
              { title: "证据", dataIndex: "hit_count" }, { title: "耗时 ms", dataIndex: "latency_ms" },
              { title: "时间", render: (_: unknown, a: QueryAudit) => new Date(a.created_at).toLocaleString() },
            ]} /> },
          ]} />
        </main>
      </div>

      <Modal title={baseModal === "edit" ? "编辑知识库" : "新建知识库"} open={baseModal !== null} onCancel={() => setBaseModal(null)} footer={null}>
        <Form form={baseForm} layout="vertical" onFinish={values => void action(async () => {
          const item = baseModal === "edit" && currentBase
            ? await api.updateBase(currentBase.id, { ...values, expected_version: currentBase.version })
            : await api.createBase(values);
          setBaseId(item.id); setBaseModal(null);
        }, "知识库已保存")}>
          <Form.Item label="名称" name="name" rules={[{ required: true, whitespace: true }]}><Input maxLength={100} /></Form.Item>
          <Form.Item label="描述" name="description"><Input.TextArea rows={3} maxLength={5000} /></Form.Item>
          <Button type="primary" htmlType="submit" loading={busy}>保存</Button>
        </Form>
      </Modal>
      <Modal title="新建向量配置" open={profileModal} onCancel={() => setProfileModal(false)} footer={null}>
        <Form form={profileForm} layout="vertical" initialValues={{ dimensions: 1024, model_revision: "1", send_dimensions: false }} onFinish={values => void action(async () => { await api.createProfile(values); setProfileModal(false); }, "配置已保存")}>
          <Form.Item label="模型服务" name="provider_id" rules={[{ required: true }]}><Select options={providers.filter(p => p.enabled).map(p => ({ value: p.id, label: p.name }))} onChange={() => profileForm.setFieldValue("model_id", undefined)} /></Form.Item>
          <Form.Item label="Embedding 模型" name="model_id" rules={[{ required: true }]}><Select options={providers.find(p => p.id === providerId)?.models.filter(m => m.enabled).map(m => ({ value: m.id, label: m.model_name }))} /></Form.Item>
          <div className="rag-form-grid two"><Form.Item label="输出维度" name="dimensions" rules={[{ required: true }]}><InputNumber min={1} max={65536} /></Form.Item><Form.Item label="配置版本" name="model_revision" rules={[{ required: true }]}><Input maxLength={100} /></Form.Item></div>
          <Form.Item label="向模型发送 dimensions 参数" name="send_dimensions" valuePropName="checked"><Switch /></Form.Item>
          <Button type="primary" htmlType="submit" loading={busy}>创建配置</Button>
        </Form>
      </Modal>
      <Modal title={selectedDocument ? "上传新版本" : "上传文档"} open={uploadModal} onCancel={() => setUploadModal(false)} footer={null}>
        <Form form={uploadForm} layout="vertical" onFinish={values => void submitUpload(values)}>
          {!selectedDocument && <Form.Item name="title" label="文档标题" rules={[{ required: true, whitespace: true }]}><Input maxLength={200} /></Form.Item>}
          <Upload.Dragger accept=".txt,.md,.markdown" maxCount={1} fileList={file ? [{ uid: "source", name: file.name, status: "done" }] : []}
            beforeUpload={next => {
              if (!/\.(txt|md|markdown)$/i.test(next.name) || next.size > 20 * 1024 * 1024 || next.size === 0) { void message.error("请选择非空 TXT / Markdown 文件，最大 20MB"); return Upload.LIST_IGNORE; }
              setFile(next); return false;
            }} onRemove={() => setFile(undefined)}>
            <UploadCloud size={28} /><p>选择 TXT / Markdown 文件</p>
          </Upload.Dragger>
          <Button className="upload-submit" type="primary" htmlType="submit" loading={busy} disabled={!file}>上传</Button>
        </Form>
      </Modal>
      <Drawer title={selectedDocument?.title} open={Boolean(selectedDocument)} width={820} onClose={() => { documentEpoch.current++; setSelectedDocument(undefined); }}>
        {selectedDocument && <div className="document-drawer">
          <div className="table-toolbar"><Text copyable={{ text: selectedDocument.id }} code>{selectedDocument.id.slice(0, 8)}</Text><Button icon={<UploadCloud size={16} />} onClick={() => { setFile(undefined); setUploadModal(true); }}>上传新版本</Button></div>
          <Select value={versionId} placeholder="选择版本" options={versions.map(v => ({ value: v.id, label: `v${v.version_number} · ${v.original_filename} · ${labels[v.status] ?? v.status}` }))} onChange={setVersionId} />
          {!versions.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无源文件版本" />}
          <section className="document-processing">
            <Title level={5}><Zap size={16} /> 文档处理</Title>
            <Form form={ingestForm} layout="vertical" onFinish={values => void action(async () => {
              if (!versionId || !profileId) throw new Error("请选择版本和向量配置");
              await api.ingest(selectedDocument.id, versionId, { ...values, profile_id: profileId });
              setTab("jobs");
            }, "处理任务已提交")}>
              <Form.Item label="向量配置"><Select value={profileId} options={profileOptions} onChange={setProfileId} placeholder="选择配置" /></Form.Item>
              <div className="rag-form-grid two"><Form.Item label="片段字符数" name="chunk_size" rules={[{ required: true }]}><InputNumber min={1} max={10000} /></Form.Item><Form.Item label="重叠字符数" name="chunk_overlap" rules={[{ required: true }]}><InputNumber min={0} max={9999} /></Form.Item></div>
              <Form.Item label="重建远端索引" name="rebuild" valuePropName="checked"><Switch /></Form.Item>
              <Button type="primary" icon={<Layers size={16} />} htmlType="submit" loading={busy} disabled={!versionId || !profileId || jobs.some(j => j.document_id === selectedDocument.id && activeJob(j))}>处理并发布</Button>
            </Form>
          </section>
          <section>
            <div className="table-toolbar"><Title level={5}>片段与发布</Title><Tooltip title="刷新文档"><Button aria-label="刷新文档" icon={<RefreshCw size={15} />} onClick={() => void openDocument(selectedDocument)} /></Tooltip></div>
            <Select value={setId} placeholder="切块批次" options={sets.map(s => ({ value: s.id, label: `${s.chunk_size} / ${s.chunk_overlap} · ${s.id.slice(0, 8)}` }))} onChange={setSetId} />
            <Space className="publication-actions" wrap>
              <Popconfirm title="发布当前批次及所选向量配置？" onConfirm={() => action(async () => {
                if (!setId || !profileId) throw new Error("请选择批次和配置");
                await api.publish(selectedDocument.id, { chunk_set_id: setId, profile_id: profileId });
              }, "文档已发布")}>
                <Button icon={<CheckCircle2 size={15} />} disabled={!setId || !profileId || busy}>发布已有索引</Button>
              </Popconfirm>
              {publications.some(p => p.document_id === selectedDocument.id) && <Popconfirm title="取消发布后该文档不再参与检索？" onConfirm={() => action(() => api.unpublish(selectedDocument.id), "已取消发布")}><Button disabled={busy}>取消发布</Button></Popconfirm>}
            </Space>
            {chunkPage.items.map(chunk => <article className="chunk-preview" key={chunk.id}><Text type="secondary">#{chunk.chunk_index + 1} · {chunk.start_char}–{chunk.end_char}</Text><p>{chunk.text}</p></article>)}
            {chunkPage.total > 0 && <Pagination current={Math.floor(chunkOffset / 10) + 1} pageSize={10} total={chunkPage.total} showSizeChanger={false} onChange={page => {
              if (!versionId || !setId) return;
              const epoch = ++chunkEpoch.current;
              setChunkOffset((page - 1) * 10);
              void api.chunks(selectedDocument.id, versionId, setId, (page - 1) * 10).then(next => { if (epoch === chunkEpoch.current) setChunkPage(next); }).catch(e => setError(errorText(e)));
            }} />}
          </section>
        </div>}
      </Drawer>
    </div>
  );
}
