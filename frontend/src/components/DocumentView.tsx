import { useEffect, useState } from "react";
import {
  fetchDocumentDetail,
  fetchDocumentPage,
  getDocumentFileUrl,
  type DocumentDetail,
  type DocumentOutlineEntry,
} from "../api";

interface DocumentViewProps {
  documentId: string;
  onClose: () => void;
}

export default function DocumentView({ documentId, onClose }: DocumentViewProps) {
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Page viewer state
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [pageText, setPageText] = useState<string>("");
  const [loadingPage, setLoadingPage] = useState<boolean>(false);
  const [viewerMode, setViewerMode] = useState<"text" | "pdf">("text");
  const [highlightTerm, setHighlightTerm] = useState<string>("");

  useEffect(() => {
    let isMounted = true;
    async function loadDoc() {
      setLoading(true);
      setError(null);
      try {
        const detail = await fetchDocumentDetail(documentId);
        if (!isMounted) return;
        setDoc(detail);
        setCurrentPage(1);
      } catch (err) {
        if (!isMounted) return;
        setError(err instanceof Error ? err.message : "Failed to load document");
      } finally {
        if (isMounted) setLoading(false);
      }
    }
    loadDoc();
    return () => {
      isMounted = false;
    };
  }, [documentId]);

  useEffect(() => {
    let isMounted = true;
    async function loadPageText() {
      if (!doc || doc.page_count === 0) return;
      setLoadingPage(true);
      try {
        const data = await fetchDocumentPage(documentId, currentPage);
        if (!isMounted) return;
        setPageText(data.text);
      } catch (err) {
        if (!isMounted) return;
        setPageText("");
      } finally {
        if (isMounted) setLoadingPage(false);
      }
    }
    if (viewerMode === "text") {
      loadPageText();
    }
    return () => {
      isMounted = false;
    };
  }, [documentId, currentPage, viewerMode, doc]);

  function handleSelectOutlineEntry(entry: DocumentOutlineEntry) {
    if (entry.page && doc && entry.page >= 1 && entry.page <= doc.page_count) {
      setCurrentPage(entry.page);
    }
  }

  function renderHighlightedText(text: string, term: string) {
    if (!term.trim()) {
      return <pre className="whitespace-pre-wrap font-sans text-xs leading-relaxed text-slate-800 dark:text-slate-200">{text || "(No extractable text on this page)"}</pre>;
    }
    const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const parts = text.split(new RegExp(`(${escaped})`, "gi"));
    return (
      <pre className="whitespace-pre-wrap font-sans text-xs leading-relaxed text-slate-800 dark:text-slate-200">
        {parts.map((part, i) =>
          part.toLowerCase() === term.toLowerCase() ? (
            <mark key={i} className="rounded bg-amber-200 px-0.5 font-semibold text-amber-900 dark:bg-amber-500/30 dark:text-amber-200">
              {part}
            </mark>
          ) : (
            part
          )
        )}
      </pre>
    );
  }

  if (loading) {
    return (
      <div className="flex h-96 items-center justify-center rounded-2xl border border-slate-200 bg-white p-8 dark:border-slate-800 dark:bg-slate-900">
        <div className="flex items-center gap-3 text-xs text-slate-500">
          <svg className="h-5 w-5 animate-spin text-emerald-600" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
          </svg>
          <span>Loading document...</span>
        </div>
      </div>
    );
  }

  if (error || !doc) {
    return (
      <div className="rounded-2xl border border-rose-200 bg-rose-50 p-6 text-center text-xs text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/40 dark:text-rose-300">
        <div className="font-semibold">{error || "Document not found"}</div>
        <button
          type="button"
          onClick={onClose}
          className="mt-4 rounded-xl border border-slate-200 bg-white px-3 py-1.5 font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-200"
        >
          Back to Sources
        </button>
      </div>
    );
  }

  const pdfUrl = `${getDocumentFileUrl(doc.id)}#page=${currentPage}`;

  return (
    <div className="space-y-6">
      {/* Top Header */}
      <div className="flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:flex-row sm:items-center sm:justify-between dark:border-slate-800 dark:bg-slate-900">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl border border-slate-200 p-2 text-slate-500 hover:bg-slate-50 dark:border-slate-800 dark:text-slate-400 dark:hover:bg-slate-800"
            title="Back to sources"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
            </svg>
          </button>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-bold text-slate-900 dark:text-white">
                {doc.filename}
              </h2>
              <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
                {doc.status}
              </span>
            </div>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {doc.page_count} pages · {(doc.size_bytes / (1024 * 1024)).toFixed(2)} MB · Uploaded {new Date(doc.created_at).toLocaleDateString()}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <a
            href={getDocumentFileUrl(doc.id)}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-800 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
            </svg>
            <span>Open PDF</span>
          </a>
        </div>
      </div>

      {/* Warnings Banner */}
      {doc.warnings && doc.warnings.length > 0 && (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-xs text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-300">
          <div className="font-semibold flex items-center gap-1.5 mb-1">
            <svg className="h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <span>Document Warnings</span>
          </div>
          <ul className="list-disc pl-5 space-y-0.5">
            {doc.warnings.map((w, idx) => (
              <li key={idx}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Main Grid: Left = Summary & Outline, Right = Page Viewer */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* Left Column: Summary & Bookmarks (5 cols) */}
        <div className="space-y-6 lg:col-span-5">
          {/* Executive Summary */}
          {doc.summary && (
            <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                  Executive Summary
                </h3>
                <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                  {doc.summary.source}
                </span>
              </div>
              <p className="text-xs leading-relaxed text-slate-700 dark:text-slate-300">
                {doc.summary.overview}
              </p>

              {/* Key Topics */}
              {doc.summary.key_topics && doc.summary.key_topics.length > 0 && (
                <div className="mt-4">
                  <div className="mb-1.5 text-[11px] font-semibold text-slate-500 dark:text-slate-400">
                    Key Topics
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {doc.summary.key_topics.map((topic, i) => (
                      <span
                        key={i}
                        className="rounded-lg border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] font-medium text-slate-700 dark:border-slate-800 dark:bg-slate-800/60 dark:text-slate-300"
                      >
                        {topic}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Suggested Questions */}
              {doc.summary.suggested_questions && doc.summary.suggested_questions.length > 0 && (
                <div className="mt-4 border-t border-slate-100 pt-3 dark:border-slate-800">
                  <div className="mb-2 text-[11px] font-semibold text-slate-500 dark:text-slate-400">
                    Suggested Questions
                  </div>
                  <ul className="space-y-1.5 text-xs text-slate-600 dark:text-slate-400">
                    {doc.summary.suggested_questions.map((q, i) => (
                      <li key={i} className="flex items-start gap-2">
                        <span className="mt-0.5 text-emerald-500 font-bold">•</span>
                        <span>{q}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {/* Bookmarks / Outline */}
          {doc.outline && doc.outline.length > 0 && (
            <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
              <h3 className="mb-3 text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                Document Outline
              </h3>
              <div className="max-h-60 space-y-1 overflow-y-auto pr-1 text-xs">
                {doc.outline.map((entry, idx) => (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => handleSelectOutlineEntry(entry)}
                    className="flex w-full items-center justify-between rounded-lg p-1.5 text-left transition hover:bg-slate-50 dark:hover:bg-slate-800"
                    style={{ paddingLeft: `${Math.max(0.375, (entry.level - 1) * 0.75)}rem` }}
                  >
                    <span className="truncate font-medium text-slate-700 dark:text-slate-300">
                      {entry.title}
                    </span>
                    {entry.page && (
                      <span className="shrink-0 text-[10px] text-slate-400">
                        p. {entry.page}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Right Column: Page Viewer (7 cols) */}
        <div className="flex flex-col rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900 lg:col-span-7">
          {/* Viewer Controls */}
          <div className="mb-4 flex flex-col gap-3 border-b border-slate-100 pb-3 sm:flex-row sm:items-center sm:justify-between dark:border-slate-800">
            {/* Mode Switcher */}
            <div className="flex rounded-xl bg-slate-100 p-1 dark:bg-slate-800">
              <button
                type="button"
                onClick={() => setViewerMode("text")}
                className={`rounded-lg px-3 py-1 text-xs font-semibold transition ${
                  viewerMode === "text"
                    ? "bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-white"
                    : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"
                }`}
              >
                Page Text
              </button>
              <button
                type="button"
                onClick={() => setViewerMode("pdf")}
                className={`rounded-lg px-3 py-1 text-xs font-semibold transition ${
                  viewerMode === "pdf"
                    ? "bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-white"
                    : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"
                }`}
              >
                Original PDF
              </button>
            </div>

            {/* Pagination Controls */}
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                disabled={currentPage <= 1}
                className="rounded-lg border border-slate-200 px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-40 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
              >
                ‹ Prev
              </button>
              <span className="text-xs font-semibold text-slate-700 dark:text-slate-300">
                Page {currentPage} of {doc.page_count}
              </span>
              <button
                type="button"
                onClick={() => setCurrentPage((p) => Math.min(doc.page_count, p + 1))}
                disabled={currentPage >= doc.page_count}
                className="rounded-lg border border-slate-200 px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-40 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
              >
                Next ›
              </button>
            </div>
          </div>

          {/* Search / Passage Highlight in Text Mode */}
          {viewerMode === "text" && (
            <div className="mb-3 flex items-center gap-2">
              <input
                type="text"
                placeholder="Highlight term or passage..."
                value={highlightTerm}
                onChange={(e) => setHighlightTerm(e.target.value)}
                className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs text-slate-800 outline-none focus:border-emerald-500 focus:bg-white dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:focus:border-emerald-500"
              />
              {highlightTerm && (
                <button
                  type="button"
                  onClick={() => setHighlightTerm("")}
                  className="rounded-lg px-2 py-1 text-xs text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                >
                  Clear
                </button>
              )}
            </div>
          )}

          {/* Viewer Area */}
          <div className="min-h-[480px] flex-1 overflow-auto rounded-xl border border-slate-200/80 bg-slate-50/50 p-4 dark:border-slate-800 dark:bg-slate-950/40">
            {viewerMode === "text" ? (
              loadingPage ? (
                <div className="flex h-64 items-center justify-center text-xs text-slate-400">
                  Loading page {currentPage}...
                </div>
              ) : (
                renderHighlightedText(pageText, highlightTerm)
              )
            ) : (
              <iframe
                src={pdfUrl}
                title={`${doc.filename} - Page ${currentPage}`}
                className="h-[560px] w-full rounded-lg border border-slate-200 dark:border-slate-800"
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
