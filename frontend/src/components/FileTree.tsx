import { useEffect, useMemo, useState } from "react";
import type { SkipReason, TreeNode, TreeStats } from "../api";

type FileKind = "code" | "notebook" | "doc" | "config" | "data" | "other";

interface FileTreeProps {
  tree: TreeNode;
  stats: TreeStats;
}

const KIND_COLORS: Record<FileKind, { text: string; badge: string; bg: string }> = {
  code: {
    text: "text-sky-600 dark:text-sky-400",
    badge: "bg-sky-50 text-sky-700 border-sky-200 dark:bg-sky-950/60 dark:text-sky-300 dark:border-sky-800",
    bg: "hover:bg-sky-50/50 dark:hover:bg-sky-950/30",
  },
  notebook: {
    text: "text-orange-600 dark:text-orange-400",
    badge: "bg-orange-50 text-orange-700 border-orange-200 dark:bg-orange-950/60 dark:text-orange-300 dark:border-orange-800",
    bg: "hover:bg-orange-50/50 dark:hover:bg-orange-950/30",
  },
  doc: {
    text: "text-emerald-600 dark:text-emerald-400",
    badge: "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/60 dark:text-emerald-300 dark:border-emerald-800",
    bg: "hover:bg-emerald-50/50 dark:hover:bg-emerald-950/30",
  },
  config: {
    text: "text-violet-600 dark:text-violet-400",
    badge: "bg-violet-50 text-violet-700 border-violet-200 dark:bg-violet-950/60 dark:text-violet-300 dark:border-violet-800",
    bg: "hover:bg-violet-50/50 dark:hover:bg-violet-950/30",
  },
  data: {
    text: "text-amber-600 dark:text-amber-400",
    badge: "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/60 dark:text-amber-300 dark:border-amber-800",
    bg: "hover:bg-amber-50/50 dark:hover:bg-amber-950/30",
  },
  other: {
    text: "text-slate-600 dark:text-slate-400",
    badge: "bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700",
    bg: "hover:bg-slate-100/50 dark:hover:bg-slate-800/30",
  },
};

function fileKind(node: TreeNode): FileKind {
  const language = node.language ?? "";
  const ext = node.ext ?? "";
  if (language === "jupyter" || ext === ".ipynb") {
    return "notebook";
  }
  if (["markdown", "text"].includes(language) || [".md", ".mdx", ".txt", ".rst"].includes(ext)) {
    return "doc";
  }
  if (
    ["json", "yaml", "dockerfile"].includes(language) ||
    [".json", ".yml", ".yaml", ".toml", ".ini", ".xml", ".env"].includes(ext) ||
    node.name.toLowerCase().startsWith("dockerfile")
  ) {
    return "config";
  }
  if (["sql"].includes(language) || [".sql", ".csv", ".tsv", ".sqlite", ".db"].includes(ext)) {
    return "data";
  }
  if (
    ["python", "javascript", "typescript", "html", "css", "shell"].includes(language) ||
    [".py", ".js", ".jsx", ".ts", ".tsx", ".sh", ".bash", ".zsh", ".html", ".css", ".scss"].includes(ext)
  ) {
    return "code";
  }
  return "other";
}

function skipLabel(reason: SkipReason | null): string {
  switch (reason) {
    case "too_large":
      return "Skipped: File exceeds 1 MB limit";
    case "binary":
      return "Skipped: Binary file format";
    case "limit_reached":
      return "Skipped: 2,000 files analysis limit reached";
    case "ignored":
      return "Skipped: Ignored directory (.git, node_modules, build, etc.)";
    default:
      return "";
  }
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function filterTree(node: TreeNode, query: string): TreeNode | null {
  if (!query) {
    return node;
  }
  if (node.type === "file") {
    return node.name.toLowerCase().includes(query) ? node : null;
  }
  const children = (node.children ?? [])
    .map((child) => filterTree(child, query))
    .filter((child): child is TreeNode => child !== null);
  if (node.name.toLowerCase().includes(query) || children.length > 0) {
    return { ...node, children };
  }
  return null;
}

function countMatchingFiles(node: TreeNode): number {
  if (node.type === "file") return 1;
  return (node.children ?? []).reduce((acc, child) => acc + countMatchingFiles(child), 0);
}

function KindIcon({ kind, className = "h-4 w-4" }: { kind: FileKind; className?: string }) {
  switch (kind) {
    case "code":
      return (
        <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
        </svg>
      );
    case "notebook":
      return (
        <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
        </svg>
      );
    case "doc":
      return (
        <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
      );
    case "config":
      return (
        <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
      );
    case "data":
      return (
        <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
        </svg>
      );
    default:
      return (
        <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
        </svg>
      );
  }
}

interface TreeItemProps {
  node: TreeNode;
  depth: number;
  forceOpen?: boolean;
}

function TreeItem({ node, depth, forceOpen }: TreeItemProps) {
  const [open, setOpen] = useState(depth < 1);

  useEffect(() => {
    if (typeof forceOpen === "boolean") {
      setOpen(forceOpen);
    }
  }, [forceOpen]);

  const kind = fileKind(node);
  const color = KIND_COLORS[kind];
  const title = skipLabel(node.skip_reason);
  const isSkipped = node.skipped;

  if (node.type === "dir") {
    return (
      <li className="select-none">
        <button
          type="button"
          title={title || undefined}
          onClick={() => setOpen((value) => !value)}
          className={`group flex w-full items-center justify-between rounded-lg px-2 py-1.5 text-left text-sm transition hover:bg-slate-100/80 dark:hover:bg-slate-800/60 ${
            isSkipped ? "opacity-50" : ""
          }`}
          style={{ paddingLeft: `${Math.max(8, depth * 18 + 8)}px` }}
        >
          <div className="flex items-center gap-2 truncate">
            {/* Folder chevron */}
            <span className="flex h-4 w-4 shrink-0 items-center justify-center text-slate-400 transition-transform duration-200">
              <svg
                className={`h-3.5 w-3.5 transition-transform duration-200 ${open ? "rotate-90 text-slate-600 dark:text-slate-300" : ""}`}
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M9 5l7 7-7 7" />
              </svg>
            </span>

            {/* Folder icon */}
            <svg
              className={`h-4 w-4 shrink-0 ${
                open ? "text-amber-500 dark:text-amber-400" : "text-amber-400 dark:text-amber-500"
              }`}
              fill="currentColor"
              viewBox="0 0 24 24"
            >
              <path d="M2.25 5.25a3 3 0 00-3 3v10.5a3 3 0 003 3h19.5a3 3 0 003-3V10.5a3 3 0 00-3-3h-9.75L10.5 5.25H2.25z" />
            </svg>

            <span className="truncate font-medium text-slate-800 dark:text-slate-200">{node.name}</span>

            {isSkipped && (
              <span className="rounded bg-slate-200/80 px-1.5 py-0.2 font-mono text-[10px] text-slate-600 dark:bg-slate-800 dark:text-slate-400">
                ignored
              </span>
            )}
          </div>

          <span className="pr-1 text-[11px] font-mono text-slate-400">
            {node.children ? `${node.children.length} items` : ""}
          </span>
        </button>

        {open && node.children && node.children.length > 0 && (
          <ul className="relative">
            {node.children.map((child) => (
              <TreeItem key={child.path} node={child} depth={depth + 1} forceOpen={forceOpen} />
            ))}
          </ul>
        )}
      </li>
    );
  }

  return (
    <li
      title={title || undefined}
      className={`group flex items-center justify-between rounded-lg px-2 py-1 text-sm transition ${color.bg} ${
        isSkipped ? "opacity-50 hover:opacity-80" : ""
      }`}
      style={{ paddingLeft: `${Math.max(26, depth * 18 + 26)}px` }}
    >
      <div className="flex items-center gap-2 truncate">
        <KindIcon kind={kind} className={`h-4 w-4 shrink-0 ${color.text}`} />
        <span className={`truncate font-mono text-xs ${isSkipped ? "text-slate-500 line-through" : color.text}`}>
          {node.name}
        </span>

        {isSkipped && node.skip_reason && (
          <span
            className="rounded border border-amber-200/80 bg-amber-50/80 px-1.5 py-0.2 font-mono text-[10px] text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/60 dark:text-amber-400"
            title={title}
          >
            {node.skip_reason}
          </span>
        )}
      </div>

      <div className="flex shrink-0 items-center gap-2 pl-2 text-[11px] font-mono text-slate-400 dark:text-slate-500">
        {node.loc !== null && !isSkipped && (
          <span title={`${node.loc} lines of code`}>
            {node.loc.toLocaleString()} loc
          </span>
        )}
        <span title={`File size: ${node.size} bytes`}>
          {formatBytes(node.size)}
        </span>
      </div>
    </li>
  );
}

export default function FileTree({ tree, stats }: FileTreeProps) {
  const [query, setQuery] = useState("");
  const [allExpanded, setAllExpanded] = useState<boolean | undefined>(undefined);

  const normalized = query.trim().toLowerCase();

  const visible = useMemo(
    () => filterTree(tree, normalized) ?? { ...tree, children: [] },
    [tree, normalized],
  );

  const matchingFileCount = useMemo(() => countMatchingFiles(visible), [visible]);

  const topLanguages = useMemo(() => {
    return Object.entries(stats.files_by_language)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5);
  }, [stats.files_by_language]);

  const totalLoc = useMemo(() => {
    function sumLoc(node: TreeNode): number {
      if (node.type === "file") return node.loc ?? 0;
      return (node.children ?? []).reduce((acc, child) => acc + sumLoc(child), 0);
    }
    return sumLoc(tree);
  }, [tree]);

  return (
    <section
      id="file-tree-section"
      className="overflow-hidden rounded-2xl border border-slate-200/80 bg-white/90 shadow-sm backdrop-blur-md dark:border-slate-800/80 dark:bg-slate-900/90"
    >
      {/* Header Statistics Card */}
      <div className="border-b border-slate-200/80 bg-slate-50/60 p-5 dark:border-slate-800/80 dark:bg-slate-950/40">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 shadow-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200">
              <svg className="h-3.5 w-3.5 text-sky-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
              </svg>
              <span>
                <strong>{stats.total_files.toLocaleString()}</strong> files
              </span>
            </div>

            <div className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 shadow-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200">
              <svg className="h-3.5 w-3.5 text-amber-500" fill="currentColor" viewBox="0 0 24 24">
                <path d="M2.25 5.25a3 3 0 00-3 3v10.5a3 3 0 003 3h19.5a3 3 0 003-3V10.5a3 3 0 00-3-3h-9.75L10.5 5.25H2.25z" />
              </svg>
              <span>
                <strong>{stats.total_directories.toLocaleString()}</strong> folders
              </span>
            </div>

            {totalLoc > 0 && (
              <div className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 shadow-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200">
                <svg className="h-3.5 w-3.5 text-indigo-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
                </svg>
                <span>
                  <strong>{totalLoc.toLocaleString()}</strong> lines of code
                </span>
              </div>
            )}

            <div className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 shadow-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200">
              <svg className="h-3.5 w-3.5 text-rose-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
              </svg>
              <span>
                <strong>{stats.skipped_count.toLocaleString()}</strong> skipped
              </span>
            </div>
          </div>

          {/* Top Languages breakdown */}
          {topLanguages.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5 text-xs">
              <span className="text-slate-400">Top languages:</span>
              {topLanguages.map(([language, count]) => (
                <span
                  key={language}
                  className="inline-flex items-center gap-1 rounded-md bg-slate-200/80 px-2 py-0.5 font-mono text-[11px] font-medium text-slate-800 dark:bg-slate-800 dark:text-slate-200"
                >
                  <span className="h-1.5 w-1.5 rounded-full bg-indigo-500" />
                  {language} <span className="opacity-60">({count})</span>
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Toolbar: Search and Expand/Collapse */}
      <div className="flex flex-col gap-2 border-b border-slate-200/80 p-4 sm:flex-row sm:items-center sm:justify-between dark:border-slate-800/80">
        <div className="relative flex-1">
          <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-slate-400">
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
          </div>

          <input
            id="file-tree-search-input"
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Filter files by name (e.g. main, test, .ts)..."
            className="w-full rounded-xl border border-slate-200 bg-white py-2 pl-9 pr-9 text-xs font-mono text-slate-900 shadow-inner placeholder:text-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
          />

          {query && (
            <button
              type="button"
              onClick={() => setQuery("")}
              className="absolute inset-y-0 right-0 flex items-center pr-3 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
              title="Clear filter"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>

        <div className="flex items-center gap-2">
          {query && (
            <span className="text-xs text-slate-500 dark:text-slate-400">
              {matchingFileCount} {matchingFileCount === 1 ? "file" : "files"} match
            </span>
          )}

          <div className="flex items-center gap-1">
            <button
              type="button"
              id="expand-all-button"
              onClick={() => setAllExpanded(true)}
              className="rounded-lg border border-slate-200 px-2.5 py-1 text-xs font-medium text-slate-700 transition hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              Expand all
            </button>
            <button
              type="button"
              id="collapse-all-button"
              onClick={() => setAllExpanded(false)}
              className="rounded-lg border border-slate-200 px-2.5 py-1 text-xs font-medium text-slate-700 transition hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              Collapse all
            </button>
          </div>
        </div>
      </div>

      {/* Interactive Tree View */}
      <div className="max-h-[620px] overflow-y-auto p-3">
        {visible.children && visible.children.length > 0 ? (
          <ul className="space-y-0.5">
            {visible.children.map((child) => (
              <TreeItem
                key={child.path}
                node={child}
                depth={0}
                forceOpen={normalized ? true : allExpanded}
              />
            ))}
          </ul>
        ) : (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <svg className="h-10 w-10 text-slate-300 dark:text-slate-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <p className="mt-3 text-sm font-medium text-slate-600 dark:text-slate-400">
              No files match "{query}"
            </p>
            <button
              type="button"
              onClick={() => setQuery("")}
              className="mt-2 text-xs font-semibold text-indigo-600 hover:text-indigo-500 dark:text-indigo-400"
            >
              Clear filter
            </button>
          </div>
        )}
      </div>

      {/* Footer Legend */}
      <div className="flex flex-wrap items-center justify-between border-t border-slate-200/80 bg-slate-50/50 px-4 py-2.5 text-[11px] text-slate-500 dark:border-slate-800/80 dark:bg-slate-950/30 dark:text-slate-400">
        <div className="flex flex-wrap items-center gap-3">
          <span className="font-semibold uppercase tracking-wider text-slate-400">Legend:</span>
          <span className="inline-flex items-center gap-1 text-sky-600 dark:text-sky-400">
            <KindIcon kind="code" className="h-3 w-3" /> Code
          </span>
          <span className="inline-flex items-center gap-1 text-orange-600 dark:text-orange-400">
            <KindIcon kind="notebook" className="h-3 w-3" /> Notebook
          </span>
          <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
            <KindIcon kind="doc" className="h-3 w-3" /> Docs
          </span>
          <span className="inline-flex items-center gap-1 text-violet-600 dark:text-violet-400">
            <KindIcon kind="config" className="h-3 w-3" /> Config
          </span>
          <span className="inline-flex items-center gap-1 text-amber-600 dark:text-amber-400">
            <KindIcon kind="data" className="h-3 w-3" /> Data
          </span>
          <span className="inline-flex items-center gap-1 text-slate-400 line-through">
            Dimmed (Skipped)
          </span>
        </div>

        <span>Hover over dimmed items for skip details</span>
      </div>
    </section>
  );
}
