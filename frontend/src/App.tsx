import { useEffect, useState } from "react";
import {
  createRepo,
  fetchTree,
  subscribeStatus,
  type PipelineStatus,
  type TreeNode,
  type TreeStats,
} from "./api";
import CodeViewer from "./components/CodeViewer";
import DependencyGraph from "./components/DependencyGraph";
import FileTree from "./components/FileTree";
import ProgressStepper from "./components/ProgressStepper";
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

  // Step 2 state: active tab ("diagram" | "tree"), selected file for CodeViewer, highlight lines
  const [activeTab, setActiveTab] = useState<"diagram" | "tree">("diagram");
  const [viewerFile, setViewerFile] = useState<string | null>(null);
  const [viewerHighlightLines, setViewerHighlightLines] = useState<[number, number] | undefined>(undefined);
  const [selectedFilePath, setSelectedFilePath] = useState<string | null>(null);

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("dark", theme === "dark");
    window.localStorage.setItem("repo_analyzer_theme", theme);
  }, [theme]);

  async function handleSubmit(url: string) {
    setActiveUrl(url);
    setRepoId(null);
    setTree(null);
    setStats(null);
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

    await new Promise<void>((resolve, reject) => {
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
            setLoadingTree(true);
            try {
              const result = await fetchTree(created.repo_id);
              setTree(result.tree);
              setStats(result.stats);
              resolve();
            } catch (err) {
              const fetchMsg = err instanceof Error ? err.message : "Failed to load file tree";
              setError(fetchMsg);
              reject(err);
            } finally {
              setLoadingTree(false);
            }
          } else if (payload.status === "failed") {
            isStopped = true;
            stop();
            resolve();
          }
        },
        (_err) => {
          // SSE connection dropped or error - EventSource retries automatically
        },
      );
    });
  }

  function handleReset() {
    setStatus(null);
    setError(null);
    setTree(null);
    setStats(null);
    setActiveUrl(null);
    setRepoId(null);
    setViewerFile(null);
    setSelectedFilePath(null);
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

  const isBusy =
    status === "cloning" ||
    status === "scanning" ||
    status === "parsing" ||
    status === "graphing" ||
    loadingTree;

  return (
    <div className="mx-auto min-h-screen max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      {/* Top Navigation / Header */}
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
                Step 2 Parser & Graph
              </span>
            </div>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Code-based visual analyzer with tree-sitter parsers, dependency graph, and code viewer
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {tree && !isBusy && (
            <button
              type="button"
              id="analyze-another-button"
              onClick={handleReset}
              className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
            >
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
              <span>Analyze Another</span>
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

      {/* Main Content Sections */}
      <main className="space-y-6">
        {/* Form */}
        <UrlForm disabled={isBusy} onSubmitUrl={handleSubmit} />

        {/* Stepper Progress */}
        {status && <ProgressStepper status={status} error={error} />}

        {/* Loading Overlay or Views */}
        {loadingTree && (
          <div className="flex items-center justify-center rounded-2xl border border-slate-200 bg-white/90 p-8 shadow-sm backdrop-blur-md dark:border-slate-800 dark:bg-slate-900/90">
            <div className="flex items-center gap-3 text-sm text-slate-600 dark:text-slate-300">
              <svg className="h-5 w-5 animate-spin text-indigo-600 dark:text-indigo-400" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <span>Fetching file tree from SQLite store…</span>
            </div>
          </div>
        )}

        {status === "ready" && repoId && tree && stats && (
          <div className="space-y-4">
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

              {/* Navigation Tabs */}
              <div className="flex items-center gap-1 rounded-lg bg-slate-100 p-1 dark:bg-slate-800">
                <button
                  type="button"
                  id="tab-diagram-button"
                  onClick={() => setActiveTab("diagram")}
                  className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1 text-xs font-semibold transition ${
                    activeTab === "diagram"
                      ? "bg-white text-indigo-600 shadow-sm dark:bg-slate-900 dark:text-indigo-400"
                      : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-200"
                  }`}
                >
                  <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z" />
                  </svg>
                  <span>Diagram</span>
                </button>

                <button
                  type="button"
                  id="tab-tree-button"
                  onClick={() => setActiveTab("tree")}
                  className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1 text-xs font-semibold transition ${
                    activeTab === "tree"
                      ? "bg-white text-indigo-600 shadow-sm dark:bg-slate-900 dark:text-indigo-400"
                      : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-200"
                  }`}
                >
                  <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                  </svg>
                  <span>File Tree</span>
                </button>
              </div>
            </div>

            {/* Main View Area */}
            <div className="relative">
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
                  onSelectFile={handleOpenFile}
                  selectedPath={selectedFilePath}
                />
              )}

              {/* Code Viewer Slide-in Panel */}
              {viewerFile && (
                <div className="fixed inset-y-0 right-0 w-full sm:w-[600px] lg:w-[680px] z-50 shadow-2xl transition-transform duration-300">
                  <CodeViewer
                    repoId={repoId}
                    filePath={viewerFile}
                    highlightLines={viewerHighlightLines}
                    onClose={() => setViewerFile(null)}
                  />
                </div>
              )}
            </div>
          </div>
        )}

        {/* Initial Empty State */}
        {!status && !tree && (
          <div className="rounded-2xl border border-dashed border-slate-300 bg-white/40 p-8 text-center backdrop-blur-sm dark:border-slate-800 dark:bg-slate-900/30">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-100 text-slate-400 dark:bg-slate-800 dark:text-slate-500">
              <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
              </svg>
            </div>
            <h3 className="mt-4 text-sm font-semibold text-slate-800 dark:text-slate-200">
              No Repository Loaded
            </h3>
            <p className="mx-auto mt-1 max-w-md text-xs text-slate-500 dark:text-slate-400">
              Submit a public GitHub URL above or click one of the sample repositories to inspect its architecture.
            </p>

            <div className="mx-auto mt-6 grid max-w-2xl grid-cols-1 gap-3 sm:grid-cols-4 text-left">
              <div className="rounded-xl border border-slate-200/80 bg-white/60 p-3.5 text-xs dark:border-slate-800 dark:bg-slate-900/60">
                <div className="font-semibold text-slate-900 dark:text-slate-100">🔒 Safe Sandbox</div>
                <div className="mt-1 text-slate-500 dark:text-slate-400 leading-relaxed">
                  Shallow depth=1 clone. Zero execution or installs.
                </div>
              </div>
              <div className="rounded-xl border border-slate-200/80 bg-white/60 p-3.5 text-xs dark:border-slate-800 dark:bg-slate-900/60">
                <div className="font-semibold text-slate-900 dark:text-slate-100">🌳 Tree-sitter AST</div>
                <div className="mt-1 text-slate-500 dark:text-slate-400 leading-relaxed">
                  Extracts functions, classes, imports, and calls.
                </div>
              </div>
              <div className="rounded-xl border border-slate-200/80 bg-white/60 p-3.5 text-xs dark:border-slate-800 dark:bg-slate-900/60">
                <div className="font-semibold text-slate-900 dark:text-slate-100">📊 Visual Diagram</div>
                <div className="mt-1 text-slate-500 dark:text-slate-400 leading-relaxed">
                  Interactive layered dependency graph with expand in place.
                </div>
              </div>
              <div className="rounded-xl border border-slate-200/80 bg-white/60 p-3.5 text-xs dark:border-slate-800 dark:bg-slate-900/60">
                <div className="font-semibold text-slate-900 dark:text-slate-100">💻 Code Viewer</div>
                <div className="mt-1 text-slate-500 dark:text-slate-400 leading-relaxed">
                  Syntax-highlighted code with line numbers and jump-to.
                </div>
              </div>
            </div>
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="mt-12 border-t border-slate-200/80 pt-6 text-center text-xs text-slate-400 dark:border-slate-800/80 dark:text-slate-500">
        <p>RepoLens • Code-Based Visual Analyzer for GitHub Repositories • Step 2</p>
      </footer>
    </div>
  );
}
