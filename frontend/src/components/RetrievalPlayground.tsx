import { useState } from "react";
import { searchRepo, type SearchResultItem } from "../api";

interface RetrievalPlaygroundProps {
  repoId: string;
  onOpenFile: (path: string, line?: number) => void;
}

export default function RetrievalPlayground({
  repoId,
  onOpenFile,
}: RetrievalPlaygroundProps) {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<"hybrid" | "vector" | "bm25">("hybrid");
  const [topK, setTopK] = useState(6);
  const [results, setResults] = useState<SearchResultItem[]>([]);
  const [confidence, setConfidence] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSearch(e?: React.FormEvent) {
    if (e) e.preventDefault();
    if (!query.trim()) return;

    setLoading(true);
    setError(null);
    try {
      const resp = await searchRepo(repoId, query.trim(), mode, topK);
      setResults(resp.results);
      setConfidence(resp.confidence);
      setSearched(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed");
    } finally {
      setLoading(false);
    }
  }

  const confidencePct = confidence !== null ? Math.round(confidence * 100) : 0;
  const confidenceColor =
    confidencePct >= 70
      ? "text-emerald-600 bg-emerald-50 dark:bg-emerald-950/60 dark:text-emerald-400 border-emerald-200"
      : confidencePct >= 40
      ? "text-amber-600 bg-amber-50 dark:bg-amber-950/60 dark:text-amber-400 border-amber-200"
      : "text-slate-600 bg-slate-50 dark:bg-slate-800 dark:text-slate-400 border-slate-200";

  return (
    <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white/95 dark:bg-slate-900/95 p-4 shadow-sm space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 dark:border-slate-800/80 pb-3">
        <div>
          <h4 className="text-xs font-bold uppercase tracking-wider text-slate-800 dark:text-slate-200">
            Semantic & Keyword Retrieval Playground
          </h4>
          <p className="text-[11px] text-slate-500 dark:text-slate-400">
            Test hybrid Reciprocal Rank Fusion (ChromaDB dense vectors + BM25 keyword matching)
          </p>
        </div>
      </div>

      {/* Query Form */}
      <form onSubmit={handleSearch} className="space-y-3">
        <div className="flex flex-col sm:flex-row gap-2">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search code semantics, functions, classes, or symbols (e.g. 'auth middleware' or 'connect db')..."
            className="flex-1 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-3 py-2 text-xs text-slate-900 dark:text-slate-100 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
          <button
            type="submit"
            disabled={loading || !query.trim()}
            className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white shadow-sm transition hover:bg-indigo-500 disabled:opacity-50"
          >
            {loading ? (
              <>
                <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white border-t-transparent" />
                <span>Searching…</span>
              </>
            ) : (
              <>
                <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
                <span>Search</span>
              </>
            )}
          </button>
        </div>

        {/* Retrieval Controls */}
        <div className="flex flex-wrap items-center justify-between gap-3 text-xs">
          <div className="flex items-center gap-2">
            <span className="font-medium text-slate-600 dark:text-slate-400">Mode:</span>
            <div className="inline-flex rounded-lg border border-slate-200 dark:border-slate-700 p-0.5 bg-slate-50 dark:bg-slate-950">
              {(
                [
                  { id: "hybrid", label: "Hybrid (RRF)" },
                  { id: "vector", label: "Vector" },
                  { id: "bm25", label: "BM25" },
                ] as const
              ).map((m) => (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => setMode(m.id)}
                  className={`rounded-md px-2.5 py-1 text-[11px] font-medium transition ${
                    mode === m.id
                      ? "bg-indigo-600 text-white shadow-xs"
                      : "text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200"
                  }`}
                >
                  {m.label}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span className="font-medium text-slate-600 dark:text-slate-400">Top K:</span>
            <div className="inline-flex rounded-lg border border-slate-200 dark:border-slate-700 p-0.5 bg-slate-50 dark:bg-slate-950">
              {[3, 6, 10].map((k) => (
                <button
                  key={k}
                  type="button"
                  onClick={() => setTopK(k)}
                  className={`rounded-md px-2 py-1 text-[11px] font-medium transition ${
                    topK === k
                      ? "bg-indigo-600 text-white shadow-xs"
                      : "text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200"
                  }`}
                >
                  {k}
                </button>
              ))}
            </div>
          </div>
        </div>
      </form>

      {error && (
        <div className="rounded-lg bg-rose-50 dark:bg-rose-950/60 p-3 text-xs text-rose-700 dark:text-rose-300">
          {error}
        </div>
      )}

      {/* Results Section */}
      {searched && (
        <div className="space-y-3 pt-2">
          <div className="flex items-center justify-between text-xs">
            <span className="font-medium text-slate-700 dark:text-slate-300">
              Matched {results.length} chunks
            </span>
            {confidence !== null && (
              <div className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold ${confidenceColor}`}>
                <span>Confidence: {confidencePct}%</span>
              </div>
            )}
          </div>

          {results.length === 0 ? (
            <div className="rounded-lg border border-dashed border-slate-200 dark:border-slate-800 p-6 text-center text-xs text-slate-500">
              No matching chunks found for query "{query}".
            </div>
          ) : (
            <div className="space-y-2 max-h-96 overflow-y-auto pr-1">
              {results.map((item, idx) => (
                <div
                  key={item.chunk_id || idx}
                  className="rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-950/50 p-3 transition hover:border-indigo-400 dark:hover:border-indigo-600 space-y-1.5"
                >
                  <div className="flex flex-wrap items-center justify-between gap-1 text-xs">
                    <button
                      type="button"
                      onClick={() => onOpenFile(item.path, item.start_line)}
                      className="font-mono font-semibold text-indigo-600 dark:text-indigo-400 hover:underline text-left truncate max-w-md"
                    >
                      {item.path}:{item.start_line}-{item.end_line}
                    </button>
                    <div className="flex items-center gap-1.5">
                      <span className="rounded bg-slate-200 dark:bg-slate-800 px-1.5 py-0.5 text-[10px] uppercase font-bold text-slate-700 dark:text-slate-300">
                        {item.kind}
                      </span>
                      {item.symbol_name && (
                        <span className="font-mono text-[10px] text-slate-500 dark:text-slate-400">
                          {item.symbol_name}
                        </span>
                      )}
                      {item.vector_rank !== null && item.vector_rank !== undefined && (
                        <span className="rounded bg-sky-100 dark:bg-sky-950/60 text-sky-800 dark:text-sky-300 px-1.5 py-0.2 text-[10px]">
                          V #{item.vector_rank}
                        </span>
                      )}
                      {item.bm25_rank !== null && item.bm25_rank !== undefined && (
                        <span className="rounded bg-amber-100 dark:bg-amber-950/60 text-amber-800 dark:text-amber-300 px-1.5 py-0.2 text-[10px]">
                          B #{item.bm25_rank}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Snippet */}
                  <pre className="overflow-x-auto rounded bg-slate-900 p-2 font-mono text-[11px] text-slate-200">
                    <code>{item.snippet}</code>
                  </pre>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
