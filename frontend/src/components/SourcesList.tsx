import { useState } from "react";
import type { DocumentListItem, RepoListItem } from "../api";

interface SourcesListProps {
  repos: RepoListItem[];
  documents: DocumentListItem[];
  selectedRepoId: string | null;
  selectedDocId: string | null;
  onSelectRepo: (repo: RepoListItem) => void;
  onSelectDoc: (doc: DocumentListItem) => void;
  onDeleteDoc: (docId: string) => Promise<void>;
}

export default function SourcesList({
  repos,
  documents,
  selectedRepoId,
  selectedDocId,
  onSelectRepo,
  onSelectDoc,
  onDeleteDoc,
}: SourcesListProps) {
  const [docToDelete, setDocToDelete] = useState<DocumentListItem | null>(null);
  const [deleting, setDeleting] = useState(false);

  async function confirmDelete() {
    if (!docToDelete) return;
    setDeleting(true);
    try {
      await onDeleteDoc(docToDelete.id);
      setDocToDelete(null);
    } finally {
      setDeleting(false);
    }
  }

  const hasSources = repos.length > 0 || documents.length > 0;

  return (
    <div className="mb-8 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="mb-4 flex items-center justify-between border-b border-slate-100 pb-3 dark:border-slate-800">
        <div className="flex items-center gap-2">
          <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600 dark:bg-indigo-950/60 dark:text-indigo-400">
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
            </svg>
          </span>
          <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            Your Sources
          </h2>
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-400">
            {repos.length + documents.length}
          </span>
        </div>
      </div>

      {!hasSources ? (
        <div className="py-6 text-center text-xs text-slate-400 dark:text-slate-500">
          No repositories or documents analyzed yet. Enter a GitHub URL or upload a PDF above.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {/* Repositories Column */}
          <div>
            <h3 className="mb-2 text-xs font-semibold text-slate-500 dark:text-slate-400">
              Repositories ({repos.length})
            </h3>
            {repos.length === 0 ? (
              <p className="text-xs text-slate-400">No repos analyzed yet.</p>
            ) : (
              <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
                {repos.map((r) => {
                  const isSelected = selectedRepoId === r.id;
                  return (
                    <button
                      key={r.id}
                      type="button"
                      onClick={() => onSelectRepo(r)}
                      className={`flex w-full items-center justify-between rounded-xl border p-2.5 text-left text-xs transition ${
                        isSelected
                          ? "border-indigo-500 bg-indigo-50/60 dark:border-indigo-500/80 dark:bg-indigo-950/30"
                          : "border-slate-200/80 bg-slate-50/50 hover:bg-slate-100/80 dark:border-slate-800 dark:bg-slate-800/40 dark:hover:bg-slate-800/80"
                      }`}
                    >
                      <div className="flex items-center gap-2 truncate">
                        <svg className="h-3.5 w-3.5 shrink-0 text-indigo-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
                        </svg>
                        <span className="truncate font-medium text-slate-800 dark:text-slate-200">
                          {r.name}
                        </span>
                      </div>
                      <span
                        className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                          r.status === "ready"
                            ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300"
                            : r.status === "failed"
                            ? "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300"
                            : "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300"
                        }`}
                      >
                        {r.status}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {/* Documents Column */}
          <div>
            <h3 className="mb-2 text-xs font-semibold text-slate-500 dark:text-slate-400">
              Documents ({documents.length})
            </h3>
            {documents.length === 0 ? (
              <p className="text-xs text-slate-400">No PDF documents uploaded yet.</p>
            ) : (
              <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
                {documents.map((d) => {
                  const isSelected = selectedDocId === d.id;
                  return (
                    <div
                      key={d.id}
                      className={`flex items-center justify-between rounded-xl border p-2.5 text-xs transition ${
                        isSelected
                          ? "border-emerald-500 bg-emerald-50/60 dark:border-emerald-500/80 dark:bg-emerald-950/30"
                          : "border-slate-200/80 bg-slate-50/50 hover:bg-slate-100/80 dark:border-slate-800 dark:bg-slate-800/40 dark:hover:bg-slate-800/80"
                      }`}
                    >
                      <button
                        type="button"
                        onClick={() => onSelectDoc(d)}
                        className="flex flex-1 items-center gap-2 truncate text-left"
                      >
                        <svg className="h-3.5 w-3.5 shrink-0 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                        </svg>
                        <span className="truncate font-medium text-slate-800 dark:text-slate-200">
                          {d.filename}
                        </span>
                        <span className="shrink-0 text-[10px] text-slate-400">
                          ({d.page_count} p)
                        </span>
                      </button>

                      <div className="flex items-center gap-2">
                        <span
                          className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                            d.status === "ready"
                              ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300"
                              : d.status === "failed"
                              ? "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300"
                              : "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300"
                          }`}
                        >
                          {d.status}
                        </span>

                        <button
                          type="button"
                          title="Delete document"
                          onClick={(e) => {
                            e.stopPropagation();
                            setDocToDelete(d);
                          }}
                          className="rounded p-1 text-slate-400 hover:bg-rose-100 hover:text-rose-600 dark:hover:bg-rose-950 dark:hover:text-rose-300"
                        >
                          <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                          </svg>
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Confirmation Modal */}
      {docToDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
          <div className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-5 shadow-xl dark:border-slate-800 dark:bg-slate-900">
            <h3 className="text-sm font-bold text-slate-900 dark:text-white">
              Delete Document?
            </h3>
            <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
              Are you sure you want to delete <span className="font-semibold text-slate-700 dark:text-slate-300">{docToDelete.filename}</span>? This will permanently remove the PDF, its extracted text, chunks, and search index.
            </p>
            <div className="mt-5 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setDocToDelete(null)}
                disabled={deleting}
                className="rounded-xl border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={confirmDelete}
                disabled={deleting}
                className="rounded-xl bg-rose-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-rose-500 disabled:opacity-50"
              >
                {deleting ? "Deleting..." : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Privacy Note */}
      <div className="mt-4 border-t border-slate-100 pt-3 text-[11px] text-slate-400 dark:border-slate-800 dark:text-slate-500">
        Uploaded files are stored on this server and removed when you delete them.
      </div>
    </div>
  );
}
