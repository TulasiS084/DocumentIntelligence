const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

export type PipelineStatus =
  | "cloning"
  | "scanning"
  | "parsing"
  | "graphing"
  | "indexing"
  | "summarizing"
  | "ready"
  | "failed";

export type SkipReason = "too_large" | "binary" | "limit_reached" | "ignored";

export interface TreeNode {
  name: string;
  path: string;
  type: "dir" | "file";
  ext: string | null;
  language: string | null;
  size: number;
  loc: number | null;
  skipped: boolean;
  skip_reason: SkipReason | null;
  summary: string | null;
  children: TreeNode[] | null;
}

export interface TreeStats {
  total_files: number;
  total_directories: number;
  files_by_language: Record<string, number>;
  skipped_count: number;
}

export interface AnalyzeResponse {
  repo_id: string;
  status: PipelineStatus;
}

export interface StatusPayload {
  status: PipelineStatus;
  error: string | null;
}

export interface TreeResponse {
  tree: TreeNode;
  stats: TreeStats;
}

// ---------------------------------------------------------------------------
// Step 2 Graph & File interfaces
// ---------------------------------------------------------------------------

export type NodeRole = "entry" | "core" | "helper" | "test" | "other";
export type EdgeKind = "import" | "call" | "data_read" | "config_ref" | "doc_link" | "test_of";

export interface GraphNode {
  id: string;
  label: string;
  folder: string;
  language: string | null;
  loc: number;
  kind: "code" | "notebook" | "doc" | "config" | "sql" | "data" | "test" | "other";
  role: NodeRole;
  in_degree: number;
  out_degree: number;
  summary: string;
  external: string[];
}

export interface GraphEdge {
  source: string;
  target: string;
  kind: EdgeKind;
  weight?: number;
  count?: number;
}

export interface FolderNode {
  id: string;
  label: string;
  files: string[];
  role: NodeRole;
  summary: string;
  file_count: number;
  loc: number;
}

export interface FolderEdge {
  source: string;
  target: string;
  kind: EdgeKind;
  count: number;
}

export interface FolderGraph {
  nodes: FolderNode[];
  edges: FolderEdge[];
}

export interface GraphOverview {
  nodes: FolderNode[];
  edges: FolderEdge[];
  entry_points: string[];
  reading_order: string[];
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  entry_points: string[];
}

export interface NodeDetail {
  id: string;
  label: string;
  path: string;
  folder: string;
  role: NodeRole;
  kind: string;
  language: string | null;
  loc: number;
  summary: string;
  external: string[];
  dependencies: string[];
  dependents: string[];
  symbols: Array<{
    name: string;
    kind: string;
    start_line: number;
    end_line: number;
  }>;
  transitive_dependents_count: number;
}

export interface ReadingOrderResponse {
  reading_order: string[];
}

export interface FileContent {
  path: string;
  language: string | null;
  loc: number | null;
  content: string;
}

export const GITHUB_URL_RE =
  /^https:\/\/github\.com\/[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?\/[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$/;

export function isValidGithubUrl(url: string): boolean {
  const trimmed = url.trim();
  const candidate = trimmed.endsWith(".git") ? trimmed.slice(0, -4) : trimmed;
  if (!GITHUB_URL_RE.test(candidate)) {
    return false;
  }
  const path = candidate.replace(/^https:\/\/github\.com\//, "");
  const [owner, repo] = path.split("/");
  if (!owner || !repo || path.split("/").length !== 2) {
    return false;
  }
  if (owner.includes("..") || repo.includes("..")) {
    return false;
  }
  return true;
}

async function parseError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string };
    if (typeof body.detail === "string") {
      return body.detail;
    }
  } catch {
    /* fall through */
  }
  return `Request failed (${response.status})`;
}

export async function createRepo(url: string): Promise<AnalyzeResponse> {
  const response = await fetch(`${API_BASE}/api/repos`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return (await response.json()) as AnalyzeResponse;
}

export function subscribeStatus(
  repoId: string,
  onEvent: (payload: StatusPayload) => void,
  onError?: (error: Event) => void,
): () => void {
  const source = new EventSource(`${API_BASE}/api/repos/${repoId}/status`);
  const handler = (event: MessageEvent<string>) => {
    try {
      const payload = JSON.parse(event.data) as StatusPayload;
      onEvent(payload);
    } catch {
      onEvent({ status: "failed", error: "Could not parse status event" });
    }
  };
  source.addEventListener("status", handler as EventListener);
  source.onmessage = handler;
  source.onerror = (event) => {
    onError?.(event);
  };
  return () => {
    source.close();
  };
}

export async function fetchTree(repoId: string): Promise<TreeResponse> {
  const response = await fetch(`${API_BASE}/api/repos/${repoId}/tree`);
  if (response.status === 409) {
    throw new Error("Repository is not ready yet");
  }
  if (response.status === 404) {
    throw new Error("Unknown repository");
  }
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return (await response.json()) as TreeResponse;
}

export async function fetchGraphOverview(repoId: string, includeHidden = false): Promise<GraphOverview> {
  const url = `${API_BASE}/api/repos/${repoId}/graph/overview?include_hidden=${includeHidden}`;
  const response = await fetch(url);
  if (response.status === 409) {
    throw new Error("Repository is not ready yet");
  }
  if (response.status === 404) {
    throw new Error("Unknown repository");
  }
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return (await response.json()) as GraphOverview;
}

export async function fetchGraphFolder(repoId: string, folder?: string, kinds = "import"): Promise<GraphData> {
  const params = new URLSearchParams();
  if (folder !== undefined) {
    params.set("folder", folder);
  }
  if (kinds) {
    params.set("kinds", kinds);
  }
  const url = `${API_BASE}/api/repos/${repoId}/graph?${params.toString()}`;
  const response = await fetch(url);
  if (response.status === 409) {
    throw new Error("Repository is not ready yet");
  }
  if (response.status === 404) {
    throw new Error("Unknown repository");
  }
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return (await response.json()) as GraphData;
}

export async function fetchGraphNode(repoId: string, nodeId: string): Promise<NodeDetail> {
  const url = `${API_BASE}/api/repos/${repoId}/graph/node?id=${encodeURIComponent(nodeId)}`;
  const response = await fetch(url);
  if (response.status === 409) {
    throw new Error("Repository is not ready yet");
  }
  if (response.status === 404) {
    throw new Error("Unknown node or repository");
  }
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return (await response.json()) as NodeDetail;
}

export async function fetchReadingOrder(repoId: string): Promise<ReadingOrderResponse> {
  const response = await fetch(`${API_BASE}/api/repos/${repoId}/reading-order`);
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return (await response.json()) as ReadingOrderResponse;
}

export async function fetchFile(repoId: string, path: string): Promise<FileContent> {
  const url = `${API_BASE}/api/repos/${repoId}/file?path=${encodeURIComponent(path)}`;
  const response = await fetch(url);
  if (response.status === 400) {
    throw new Error("Invalid file path");
  }
  if (response.status === 404) {
    throw new Error("File not found or was skipped");
  }
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return (await response.json()) as FileContent;
}

export interface ProjectSummary {
  repo_id: string;
  overview: string | null;
  stack: string[] | null;
  how_to_run: string | null;
  folder_guide: Record<string, string> | null;
  key_files: string[] | null;
  source: "llm" | "deterministic";
}

export interface SearchResultItem {
  chunk_id: string;
  path: string;
  language: string | null;
  kind: string;
  symbol_name: string | null;
  start_line: number;
  end_line: number;
  snippet: string;
  score: number;
  vector_rank: number | null;
  bm25_rank: number | null;
}

export interface SearchResponse {
  repo_id: string;
  query: string;
  mode: string;
  confidence: number;
  results: SearchResultItem[];
}

export async function fetchSummary(repoId: string): Promise<ProjectSummary> {
  const response = await fetch(`${API_BASE}/api/repos/${repoId}/summary`);
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return (await response.json()) as ProjectSummary;
}

export async function searchRepo(
  repoId: string,
  query: string,
  mode: "hybrid" | "vector" | "bm25" = "hybrid",
  topK = 6
): Promise<SearchResponse> {
  const response = await fetch(`${API_BASE}/api/repos/${repoId}/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, mode, top_k: topK }),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return (await response.json()) as SearchResponse;
}
