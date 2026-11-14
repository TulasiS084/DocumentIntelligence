import { useEffect, useState } from "react";
import {
  createRepo,
  deleteDocument,
  fetchDocuments,
  fetchRepos,
  fetchSummary,
  fetchTree,
  subscribeDocumentStatus,
  subscribeStatus,
  type DocPipelineStatus,
  type DocumentListItem,
  type DocumentUploadItem,
  type PipelineStatus,
  type ProjectSummary,
  type RepoListItem,
  type TreeNode,
  type TreeStats,
} from "./api";
import CodeViewer from "./components/CodeViewer";
import DependencyGraph from "./components/DependencyGraph";
import DocumentProgressStepper from "./components/DocumentProgressStepper";
import DocumentView from "./components/DocumentView";
import FileTree from "./components/FileTree";
import PdfUploadCard from "./components/PdfUploadCard";
import ProgressStepper from "./components/ProgressStepper";
import RetrievalPlayground from "./components/RetrievalPlayground";
import SourcesList from "./components/SourcesList";
import SummaryPanel from "./components/SummaryPanel";
import UrlForm from "./components/UrlForm";

function getPreferredTheme(): "light" | "dark" {
  if (typeof window === "undefined") {
    return "dark";
  }
  const stored = window.localStorage.getItem("repo_analyzer_theme");
  if (stored === "light" || stored === "dark") {
    return stored;
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

export default function App() {
  const [theme, setTheme] = useState<"light" | "dark">(getPreferredTheme);
  const [activeUrl, setActiveUrl] = useState<string | null>(null);
  const [repoId, setRepoId] = useState<string | null>(null);
  const [status, setStatus] = useState<PipelineStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tree, setTree] = useState<TreeNode | null>(null);
  const [stats, setStats] = useState<TreeStats | null>(null);
  const [loadingTree, setLoadingTree] = useState(false);
  const [summary, setSummary] = useState<ProjectSummary | null>(null);
  const [loadingSummary, setLoadingSummary] = useState(false);

  // Document states
  const [repos, setRepos] = useState<RepoListItem[]>([]);
  const [documents, setDocuments] = useState<DocumentListItem[]>([]);
  const [activeDocId, setActiveDocId] = useState<string | null>(null);
  const [docStatus, setDocStatus] = useState<DocPipelineStatus | null>(null);
  const [docError, setDocError] = useState<string | null>(null);

  // Tab & Viewer states for Repos
  const [activeTab, setActiveTab] = useState<"diagram" | "tree">("diagram");
  const [viewerFile, setViewerFile] = useState<string | null>(null);
  const [viewerHighlightLines, setViewerHighlightLines] = useState<[number, number] | undefined>(undefined);
  const [selectedFilePath, setSelectedFilePath] = useState<string | null>(null);

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("dark", theme === "dark");
    window.localStorage.setItem("repo_analyzer_theme", theme);
  }, [theme]);

  // Load existing repos and documents
  async function refreshSources() {
    try {
      const [rList, dList] = await Promise.allSettled([fetchRepos(), fetchDocuments()]);
      if (rList.status === "fulfilled") setRepos(rList.value);
      if (dList.status === "fulfilled") setDocuments(dList.value);
    } catch {
      // Ignore background fetch failures
    }
  }

  useEffect(() => {
    refreshSources();
  }, []);

  async function loadRepoData(id: string) {
    setLoadingTree(true);
    setLoadingSummary(true);
    try {
      const [treeResult, summaryResult] = await Promise.allSettled([
        fetchTree(id),
        fetchSummary(id),
      ]);
      if (treeResult.status === "fulfilled") {
        setTree(treeResult.value.tree);
        setStats(treeResult.value.stats);
      }
      if (summaryResult.status === "fulfilled") {
        setSummary(summaryResult.value);
      }
    } catch (err) {
      const fetchMsg = err instanceof Error ? err.message : "Failed to load repo data";
      setError(fetchMsg);
    } finally {
      setLoadingTree(false);
      setLoadingSummary(false);
    }
  }

  async function handleSubmit(url: string) {
    setActiveDocId(null);
    setDocStatus(null);
    setActiveUrl(url);
    setRepoId(null);
    setTree(null);
    setStats(null);
    setSummary(null);
    setError(null);
    setStatus("cloning");
    setViewerFile(null);
    setSelectedFilePath(null);

    let created: Awaited<ReturnType<typeof createRepo>>;
    try {
      created = await createRepo(url);
      setRepoId(created.repo_id);
    } catch (err) {
      setStatus("failed");
      const message = err instanceof Error ? err.message : "Failed to queue analysis";
      setError(message);
      throw err;
    }

    await new Promise<void>((resolve) => {
      let isStopped = false;
      const stop = subscribeStatus(
        created.repo_id,
        async (payload) => {
          if (isStopped) return;
          setStatus(payload.status);
          setError(payload.error);

          if (payload.status === "ready") {
            isStopped = true;
            stop();
            await loadRepoData(created.repo_id);
            refreshSources();
            resolve();
          } else if (payload.status === "failed") {
            isStopped = true;
            stop();
            refreshSources();
            resolve();
          }
        },
        (_err) => {
          // SSE retry handled automatically
        }
      );
    });
  }

  function handleReset() {
    setStatus(null);
    setError(null);
    setTree(null);
    setStats(null);
    setSummary(null);
    setActiveUrl(null);
    setRepoId(null);
    setActiveDocId(null);
    setDocStatus(null);
    setDocError(null);
    setViewerFile(null);
    setSelectedFilePath(null);
    refreshSources();
  }

  function handleSelectRepo(r: RepoListItem) {
    setActiveDocId(null);
    setDocStatus(null);
    setRepoId(r.id);
    setActiveUrl(r.url);
    setStatus(r.status);
    setError(r.error);
    setViewerFile(null);
    setSelectedFilePath(null);

    if (r.status === "ready") {
      loadRepoData(r.id);
    } else if (r.status !== "failed") {
      const stop = subscribeStatus(r.id, (payload) => {
        setStatus(payload.status);
        setError(payload.error);
        if (payload.status === "ready") {
          stop();
          loadRepoData(r.id);
          refreshSources();
        } else if (payload.status === "failed") {
          stop();
          refreshSources();
        }
      });
    }
  }

  function handleSelectDoc(d: DocumentListItem) {
    setRepoId(null);
    setStatus(null);
    setActiveDocId(d.id);
    setDocStatus(d.status);
    setDocError(d.error);

    if (d.status !== "ready" && d.status !== "failed") {
      const stop = subscribeDocumentStatus(d.id, (payload) => {
        setDocStatus(payload.status);
        setDocError(payload.error);
        if (payload.status === "ready" || payload.status === "failed") {
          stop();
          refreshSources();
        }
      });
    }
  }

  function handleUploadedDocs(uploaded: DocumentUploadItem[]) {
    refreshSources();
    const successful = uploaded.filter((u) => u.document_id);
    if (successful.length > 0) {
      const first = successful[0];
      setRepoId(null);
      setStatus(null);
      setActiveDocId(first.document_id);
      setDocStatus(first.status);
      setDocError(first.error);

      if (first.status !== "ready" && first.status !== "failed") {
        const stop = subscribeDocumentStatus(first.document_id, (payload) => {
          setDocStatus(payload.status);
          setDocError(payload.error);
          if (payload.status === "ready" || payload.status === "failed") {
            stop();
            refreshSources();
          }
        });
      }
    }
  }

  async function handleDeleteDocument(docId: string) {
    await deleteDocument(docId);
    if (activeDocId === docId) {
      setActiveDocId(null);
      setDocStatus(null);
    }
    refreshSources();
  }

  function handleOpenFile(path: string, line?: number) {
    setSelectedFilePath(path);
    setViewerFile(path);
    if (line !== undefined) {
      setViewerHighlightLines([line, line]);
    } else {
      setViewerHighlightLines(undefined);
    }
  }

  const isRepoBusy =
    status === "cloning" ||
    status === "scanning" ||
    status === "parsing" ||
    status === "graphing" ||
    status === "indexing" ||
    status === "summarizing" ||
    loadingTree;

  const isDocBusy =
    docStatus === "uploading" ||
    docStatus === "extracting" ||
    docStatus === "chunking" ||
    docStatus === "indexing" ||
    docStatus === "summarizing";

  const showingDetails = (repoId && status === "ready") || (activeDocId && docStatus === "ready");

  return (
    <div className="mx-auto min-h-screen max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      {/* Top Header */}
      <header className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-tr from-indigo-600 to-indigo-400 text-white shadow-md shadow-indigo-500/30">
            <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
            </svg>
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold tracking-tight text-slate-900 dark:text-white sm:text-2xl">
                RepoLens
              </h1>
              <span className="rounded-full border border-indigo-200 bg-indigo-50 px-2 py-0.5 text-[10px] font-semibold text-indigo-700 dark:border-indigo-900/60 dark:bg-indigo-950/60 dark:text-indigo-300">
                Step 4A PDF Documents & Code Analysis
              </span>
            </div>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Visual codebase analyzer, tree-sitter parsers, PDF document indexer & hybrid semantic search
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {(showingDetails || isRepoBusy || isDocBusy) && (
            <button
              type="button"
              id="analyze-another-button"
              onClick={handleReset}
              className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
            >
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
              </svg>
              <span>Back to Sources</span>
            </button>
          )}

          <button
            id="theme-toggle-button"
            type="button"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white/80 px-3 py-1.5 text-xs font-medium text-slate-700 shadow-sm backdrop-blur-sm transition hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900/80 dark:text-slate-300 dark:hover:bg-slate-800"
            aria-label="Toggle theme"
          >
            {theme === "dark" ? (
              <>
                <svg className="h-4 w-4 text-amber-400" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M10 2a1 1 0 011 1v1a1 1 0 11-2 0V3a1 1 0 011-1zm4 8a4 4 0 11-8 0 4 4 0 018 0zm-.464 4.95l.707.707a1 1 0 001.414-1.414l-.707-.707a1 1 0 00-1.414 1.414zm2.12-10.607a1 1 0 010 1.414l-.706.707a1 1 0 11-1.414-1.414l.707-.707a1 1 0 011.414 0zM17 11a1 1 0 100-2h-1a1 1 0 100 2h1zm-7 4a1 1 0 011 1v1a1 1 0 11-2 0v-1a1 1 0 011-1zM5.05 6.464A1 1 0 106.465 5.05l-.708-.707a1 1 0 00-1.414 1.414l.707.707zm1.414 8.486l-.707.707a1 1 0 01-1.414-1.414l.707-.707a1 1 0 011.414 1.414zM4 11a1 1 0 100-2H3a1 1 0 000 2h1z" clipRule="evenodd" />
                </svg>
                <span>Light</span>
              </>
            ) : (
              <>
                <svg className="h-4 w-4 text-indigo-500" fill="currentColor" viewBox="0 0 20 20">
                  <path d="M17.293 13.293A8 8 0 016.707 2.707a8.001 8.001 0 1010.586 10.586z" />
                </svg>
                <span>Dark</span>
              </>
            )}
          </button>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="space-y-6">
        {/* If viewing a selected Document */}
        {activeDocId && docStatus === "ready" ? (
          <DocumentView documentId={activeDocId} onClose={handleReset} />
        ) : activeDocId && isDocBusy ? (
          <DocumentProgressStepper status={docStatus} error={docError} />
        ) : repoId && status === "ready" && tree && stats ? (
          /* If viewing a selected Repo */
          <div className="space-y-4">
            <SummaryPanel
              summary={summary}
              isLoading={loadingSummary}
              onSelectFile={handleOpenFile}
            />

            {/* Context bar with URL and View Tabs */}
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200/80 bg-white/60 px-4 py-2 text-xs backdrop-blur-sm dark:border-slate-800/80 dark:bg-slate-900/60">
              <div className="flex items-center gap-2 truncate">
                <span className="text-slate-400">Inspecting:</span>
                <a
                  href={activeUrl || "#"}
                  target="_blank"
                  rel="noreferrer"
                  className="font-mono font-medium text-indigo-600 hover:underline dark:text-indigo-400 truncate max-w-sm"
                >
                  {activeUrl}
                </a>
              </div>

              <div className="flex items-center gap-2">
                <div className="flex rounded-lg bg-slate-100 p-0.5 dark:bg-slate-800">
                  <button
                    type="button"
                    onClick={() => setActiveTab("diagram")}
                    className={`rounded-md px-3 py-1 font-medium transition ${
                      activeTab === "diagram"
                        ? "bg-white text-indigo-700 shadow-sm dark:bg-slate-700 dark:text-white"
                        : "text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"
                    }`}
                  >
                    Interactive Diagram
                  </button>
                  <button
                    type="button"
                    onClick={() => setActiveTab("tree")}
                    className={`rounded-md px-3 py-1 font-medium transition ${
                      activeTab === "tree"
                        ? "bg-white text-indigo-700 shadow-sm dark:bg-slate-700 dark:text-white"
                        : "text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"
                    }`}
                  >
                    File Tree
                  </button>
                </div>
              </div>
            </div>

            {/* RAG Retrieval Playground */}
            <RetrievalPlayground repoId={repoId} onOpenFile={handleOpenFile} />

            {/* View Tabs */}
            {activeTab === "diagram" ? (
              <DependencyGraph
                repoId={repoId}
                onOpenFile={handleOpenFile}
                selectedFilePath={selectedFilePath}
              />
            ) : (
              <FileTree
                tree={tree}
                stats={stats}
                onSelectFile={(path) => handleOpenFile(path)}
                selectedPath={selectedFilePath}
              />
            )}
          </div>
        ) : (
          /* Home Screen: Two cards side by side + Sources List */
          <div className="space-y-8">
            <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
              <UrlForm disabled={isRepoBusy || isDocBusy} onSubmitUrl={handleSubmit} />
              <PdfUploadCard disabled={isRepoBusy || isDocBusy} onUploaded={handleUploadedDocs} />
            </div>

            {status && isRepoBusy && <ProgressStepper status={status} error={error} />}

            <SourcesList
              repos={repos}
              documents={documents}
              selectedRepoId={repoId}
              selectedDocId={activeDocId}
              onSelectRepo={handleSelectRepo}
              onSelectDoc={handleSelectDoc}
              onDeleteDoc={handleDeleteDocument}
            />
          </div>
        )}

        {/* CodeViewer Drawer */}
        {viewerFile && repoId && (
          <CodeViewer
            repoId={repoId}
            filePath={viewerFile}
            highlightLines={viewerHighlightLines}
            onClose={() => setViewerFile(null)}
          />
        )}
      </main>
    </div>
  );
}
