import { useEffect, useState } from "react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark, oneLight } from "react-syntax-highlighter/dist/esm/styles/prism";
import { fetchFile, type FileContent } from "../api";

interface CodeViewerProps {
  repoId: string;
  filePath: string | null;
  highlightLines?: [number, number];
  onClose: () => void;
}

export default function CodeViewer({
  repoId,
  filePath,
  highlightLines,
  onClose,
}: CodeViewerProps) {
  const [fileData, setFileData] = useState<FileContent | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Detect dark mode from documentElement class
  const isDark = typeof document !== "undefined" && document.documentElement.classList.contains("dark");

  useEffect(() => {
    if (!filePath || !repoId) {
      setFileData(null);
      setError(null);
      return;
    }

    let isMounted = true;
    setLoading(true);
    setError(null);

    fetchFile(repoId, filePath)
      .then((data) => {
        if (isMounted) {
          setFileData(data);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (isMounted) {
          setError(err instanceof Error ? err.message : "Failed to load file content");
          setLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [repoId, filePath]);

  if (!filePath) {
    return null;
  }

  // Map language to Prism language identifier
  function mapLanguage(lang: string | null): string {
    if (!lang) return "text";
    const l = lang.toLowerCase();
    if (l === "python") return "python";
    if (l === "javascript" || l === "js") return "javascript";
    if (l === "typescript" || l === "ts") return "typescript";
    if (l === "json") return "json";
    if (l === "markdown" || l === "md") return "markdown";
    if (l === "yaml" || l === "yml") return "yaml";
    if (l === "sql") return "sql";
    if (l === "html") return "html";
    if (l === "css") return "css";
    if (l === "shell" || l === "bash" || l === "sh") return "bash";
    if (l === "dockerfile") return "dockerfile";
    return "text";
  }

  return (
    <div
      id="code-viewer-panel"
      className="flex flex-col h-full bg-white dark:bg-slate-900 border-l border-slate-200 dark:border-slate-800 shadow-2xl z-20"
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-200 dark:border-slate-800 px-4 py-3 bg-slate-50/80 dark:bg-slate-950/50 backdrop-blur-sm">
        <div className="flex items-center gap-2 truncate">
          <svg className="h-4 w-4 shrink-0 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          <span className="font-mono text-xs font-semibold text-slate-800 dark:text-slate-200 truncate" title={filePath}>
            {filePath}
          </span>
          {fileData?.language && (
            <span className="rounded bg-indigo-50 dark:bg-indigo-950/60 text-indigo-700 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-800/60 px-1.5 py-0.5 text-[10px] font-mono">
              {fileData.language}
            </span>
          )}
          {fileData?.loc !== null && fileData?.loc !== undefined && (
            <span className="text-[11px] font-mono text-slate-400">
              {fileData.loc} lines
            </span>
          )}
        </div>

        <button
          type="button"
          onClick={onClose}
          className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-200/60 dark:hover:bg-slate-800 hover:text-slate-600 dark:hover:text-slate-200 transition"
          title="Close viewer"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto text-xs font-mono">
        {loading && (
          <div className="flex h-64 items-center justify-center gap-2 text-slate-500">
            <svg className="h-5 w-5 animate-spin text-indigo-600" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <span>Loading code…</span>
          </div>
        )}

        {error && (
          <div className="p-6 text-center">
            <div className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-rose-100 dark:bg-rose-950/60 text-rose-600 mb-2">
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
            </div>
            <p className="text-sm font-medium text-rose-600 dark:text-rose-400">{error}</p>
            <p className="mt-1 text-xs text-slate-400">
              Binary files, files over 1 MB, or ignored paths are not stored.
            </p>
          </div>
        )}

        {!loading && !error && fileData && (
          <SyntaxHighlighter
            language={mapLanguage(fileData.language)}
            style={isDark ? oneDark : oneLight}
            showLineNumbers
            wrapLines
            lineProps={(lineNumber) => {
              const isHighlighted =
                highlightLines &&
                lineNumber >= highlightLines[0] &&
                lineNumber <= highlightLines[1];
              return {
                style: {
                  display: "block",
                  backgroundColor: isHighlighted ? (isDark ? "rgba(234, 179, 8, 0.2)" : "rgba(254, 240, 138, 0.6)") : undefined,
                  borderLeft: isHighlighted ? "3px solid #eab308" : undefined,
                },
              };
            }}
            customStyle={{
              margin: 0,
              padding: "1rem",
              background: "transparent",
              fontSize: "12px",
              lineHeight: "1.6",
            }}
          >
            {fileData.content || "// File is empty"}
          </SyntaxHighlighter>
        )}
      </div>
    </div>
  );
}
