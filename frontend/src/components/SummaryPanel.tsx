import { useState } from "react";
import type { ProjectSummary } from "../api";

interface SummaryPanelProps {
  summary: ProjectSummary | null;
  isLoading: boolean;
  onSelectFile?: (path: string) => void;
}

type TabType = "overview" | "stack" | "run" | "folders" | "key_files";

export default function SummaryPanel({
  summary,
  isLoading,
  onSelectFile,
}: SummaryPanelProps) {
  const [activeTab, setActiveTab] = useState<TabType>("overview");

  if (isLoading) {
    return (
      <div className="rounded-2xl border border-slate-200/80 bg-white/90 p-6 shadow-sm backdrop-blur-md dark:border-slate-800/80 dark:bg-slate-900/90">
        <div className="flex items-center gap-3">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-indigo-500 border-t-transparent" />
          <span className="text-sm text-slate-500 dark:text-slate-400">Loading architecture summary...</span>
        </div>
      </div>
    );
  }

  if (!summary) {
    return null;
  }

  const isLlm = summary.source === "llm";

  return (
    <div className="rounded-2xl border border-slate-200/80 bg-white/90 p-6 shadow-sm backdrop-blur-md dark:border-slate-800/80 dark:bg-slate-900/90">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 pb-3 dark:border-slate-800">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
            Repository Architecture & Insights
          </h2>
          <span
            className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
              isLlm
                ? "bg-purple-100 text-purple-700 dark:bg-purple-950/60 dark:text-purple-300"
                : "bg-amber-100 text-amber-700 dark:bg-amber-950/60 dark:text-amber-300"
            }`}
          >
            {isLlm ? "✨ AI Generated" : "⚡ Deterministic"}
          </span>
        </div>

        {/* Tab navigation */}
        <div className="flex gap-1">
          {(
            [
              { id: "overview", label: "Overview" },
              { id: "stack", label: "Tech Stack" },
              { id: "run", label: "How to Run" },
              { id: "folders", label: "Folder Guide" },
              { id: "key_files", label: "Key Files" },
            ] as const
          ).map((t) => (
            <button
              key={t.id}
              onClick={() => setActiveTab(t.id)}
              className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                activeTab === t.id
                  ? "bg-indigo-600 text-white shadow-sm"
                  : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab Contents */}
      <div className="text-sm leading-relaxed text-slate-700 dark:text-slate-300">
        {activeTab === "overview" && (
          <div className="space-y-3">
            <p className="whitespace-pre-wrap">{summary.overview || "No overview provided."}</p>
            {summary.stack && summary.stack.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5 pt-2">
                <span className="text-xs font-semibold text-slate-500">Stack:</span>
                {summary.stack.map((item, idx) => (
                  <span
                    key={idx}
                    className="rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-700 dark:bg-slate-800 dark:text-slate-200"
                  >
                    {item}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        {activeTab === "stack" && (
          <div>
            <div className="flex flex-wrap gap-2">
              {summary.stack && summary.stack.length > 0 ? (
                summary.stack.map((item, idx) => (
                  <div
                    key={idx}
                    className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50/50 px-3 py-1.5 text-xs font-medium text-slate-700 dark:border-slate-800 dark:bg-slate-800/50 dark:text-slate-200"
                  >
                    <span className="h-2 w-2 rounded-full bg-indigo-500" />
                    {item}
                  </div>
                ))
              ) : (
                <span className="text-slate-400">No technology tags available.</span>
              )}
            </div>
          </div>
        )}

        {activeTab === "run" && (
          <div className="space-y-2">
            <div className="rounded-lg bg-slate-950 p-3 font-mono text-xs text-slate-200">
              <code>{summary.how_to_run || "No run instructions available."}</code>
            </div>
          </div>
        )}

        {activeTab === "folders" && (
          <div className="space-y-2">
            {summary.folder_guide && Object.keys(summary.folder_guide).length > 0 ? (
              <div className="grid gap-2 sm:grid-cols-2">
                {Object.entries(summary.folder_guide).map(([folder, desc]) => (
                  <div
                    key={folder}
                    className="rounded-lg border border-slate-200/70 bg-slate-50/30 p-2.5 dark:border-slate-800 dark:bg-slate-800/30"
                  >
                    <div className="font-mono text-xs font-semibold text-indigo-600 dark:text-indigo-400">
                      {folder}/
                    </div>
                    <div className="mt-1 text-xs text-slate-600 dark:text-slate-400">{desc}</div>
                  </div>
                ))}
              </div>
            ) : (
              <span className="text-slate-400">No folder guide generated.</span>
            )}
          </div>
        )}

        {activeTab === "key_files" && (
          <div className="space-y-1.5">
            {summary.key_files && summary.key_files.length > 0 ? (
              summary.key_files.map((file, idx) => (
                <div
                  key={idx}
                  onClick={() => onSelectFile?.(file)}
                  className="flex cursor-pointer items-center justify-between rounded-lg px-2.5 py-1.5 text-xs transition-colors hover:bg-slate-100 dark:hover:bg-slate-800"
                >
                  <span className="font-mono text-indigo-600 dark:text-indigo-400">{file}</span>
                  <span className="text-[11px] text-slate-400">View code →</span>
                </div>
              ))
            ) : (
              <span className="text-slate-400">No key files designated.</span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
