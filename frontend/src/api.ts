const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

export type PipelineStatus = "cloning" | "scanning" | "ready" | "failed";

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
  summary: null;
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
