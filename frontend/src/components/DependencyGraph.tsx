import { useCallback, useEffect, useRef, useState } from "react";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
} from "@xyflow/react";
import dagre from "@dagrejs/dagre";
import { toPng } from "html-to-image";
import {
  fetchGraphFolder,
  fetchGraphNode,
  fetchGraphOverview,
  fetchReadingOrder,
  type EdgeKind,
  type FolderEdge,
  type FolderNode,
  type GraphEdge,
  type GraphNode,
  type NodeDetail,
  type NodeRole,
} from "../api";

interface DependencyGraphProps {
  repoId: string;
  onOpenFile: (path: string, line?: number) => void;
  selectedFilePath?: string | null;
}

const ROLE_COLORS: Record<NodeRole, { border: string; bg: string; text: string; badge: string }> = {
  entry: {
    border: "border-emerald-500",
    bg: "bg-emerald-50/90 dark:bg-emerald-950/50",
    text: "text-emerald-900 dark:text-emerald-100",
    badge: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/80 dark:text-emerald-200",
  },
  core: {
    border: "border-sky-500",
    bg: "bg-sky-50/90 dark:bg-sky-950/50",
    text: "text-sky-900 dark:text-sky-100",
    badge: "bg-sky-100 text-sky-800 dark:bg-sky-900/80 dark:text-sky-200",
  },
  helper: {
    border: "border-amber-500",
    bg: "bg-amber-50/90 dark:bg-amber-950/50",
    text: "text-amber-900 dark:text-amber-100",
    badge: "bg-amber-100 text-amber-800 dark:bg-amber-900/80 dark:text-amber-200",
  },
  test: {
    border: "border-rose-400",
    bg: "bg-rose-50/90 dark:bg-rose-950/50",
    text: "text-rose-900 dark:text-rose-100",
    badge: "bg-rose-100 text-rose-800 dark:bg-rose-900/80 dark:text-rose-200",
  },
  other: {
    border: "border-slate-300 dark:border-slate-700",
    bg: "bg-slate-50/90 dark:bg-slate-900/60",
    text: "text-slate-800 dark:text-slate-200",
    badge: "bg-slate-200 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  },
};

const EDGE_STYLES: Record<
  EdgeKind,
  { stroke: string; strokeDasharray?: string; label: string }
> = {
  import: { stroke: "#6366f1", label: "Imports" },
  call: { stroke: "#a855f7", strokeDasharray: "4 3", label: "Calls" },
  data_read: { stroke: "#f59e0b", strokeDasharray: "3 3", label: "Data Read" },
  config_ref: { stroke: "#8b5cf6", label: "Config Ref" },
  doc_link: { stroke: "#10b981", strokeDasharray: "2 2", label: "Doc Link" },
  test_of: { stroke: "#f43f5e", strokeDasharray: "3 2", label: "Tests" },
};

// ---------------------------------------------------------------------------
// Custom Node Component
// ---------------------------------------------------------------------------

function CustomNodeComponent({ data }: { data: any }) {
  const isFolder = data.isFolder;
  const role: NodeRole = data.role || "other";
  const colors = ROLE_COLORS[role] || ROLE_COLORS.other;
  const isSelected = data.isSelected;
  const isDimmed = data.isDimmed;

  return (
    <div
      className={`relative min-w-[220px] max-w-[280px] rounded-xl border-2 p-3 text-left shadow-md transition-all duration-200 backdrop-blur-sm ${
        colors.border
      } ${colors.bg} ${
        isSelected
          ? "ring-4 ring-indigo-500/40 shadow-indigo-500/20 scale-105 z-20"
          : isDimmed
          ? "opacity-30 grayscale"
          : "hover:shadow-lg hover:-translate-y-0.5"
      }`}
    >
      <Handle type="target" position={Position.Left} className="!w-2 !h-2 !bg-indigo-500" />

      {/* Header */}
      <div className="flex items-center justify-between gap-1 mb-1">
        <div className="flex items-center gap-1.5 truncate">
          {isFolder ? (
            <svg className="h-4 w-4 shrink-0 text-amber-500" fill="currentColor" viewBox="0 0 24 24">
              <path d="M2.25 5.25a3 3 0 00-3 3v10.5a3 3 0 003 3h19.5a3 3 0 003-3V10.5a3 3 0 00-3-3h-9.75L10.5 5.25H2.25z" />
            </svg>
          ) : (
            <svg className="h-4 w-4 shrink-0 text-sky-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
            </svg>
          )}
          <span className="font-mono text-xs font-bold truncate text-slate-900 dark:text-slate-100">
            {data.label}
          </span>
        </div>

        <div className="flex items-center gap-1 shrink-0">
          {data.isEntry && (
            <span className="rounded bg-emerald-600 px-1.5 py-0.2 text-[9px] font-bold text-white uppercase tracking-wider animate-pulse">
              ▶ START
            </span>
          )}
          <span className={`rounded px-1.5 py-0.2 text-[9px] font-semibold uppercase ${colors.badge}`}>
            {role}
          </span>
        </div>
      </div>

      {/* Summary */}
      <p className="text-[11px] text-slate-600 dark:text-slate-300 line-clamp-2 leading-relaxed">
        {data.summary || (isFolder ? "Folder package" : "Source file")}
      </p>

      {/* Stats footer */}
      <div className="mt-2.5 flex items-center justify-between pt-1.5 border-t border-slate-200/60 dark:border-slate-800 text-[10px] text-slate-500 dark:text-slate-400">
        <span>
          {isFolder ? `${data.fileCount || 0} files` : `${data.loc || 0} lines`}
        </span>
        {isFolder ? (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              data.onToggleFolder?.(data.id);
            }}
            className="font-medium text-indigo-600 dark:text-indigo-400 hover:underline inline-flex items-center gap-0.5"
          >
            {data.isExpanded ? "▲ Collapse" : "▼ Expand in place"}
          </button>
        ) : (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              data.onOpenCode?.(data.id);
            }}
            className="font-medium text-indigo-600 dark:text-indigo-400 hover:underline"
          >
            Open code →
          </button>
        )}
      </div>

      <Handle type="source" position={Position.Right} className="!w-2 !h-2 !bg-indigo-500" />
    </div>
  );
}

const nodeTypes = {
  custom: CustomNodeComponent,
};

// ---------------------------------------------------------------------------
// Dagre Auto-Layout Helper
// ---------------------------------------------------------------------------

function layoutElements(nodes: Node[], edges: Edge[]) {
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));
  dagreGraph.setGraph({ rankdir: "LR", nodesep: 50, ranksep: 90 });

  nodes.forEach((node) => {
    dagreGraph.setNode(node.id, { width: 250, height: 110 });
  });

  edges.forEach((edge) => {
    dagreGraph.setEdge(edge.source, edge.target);
  });

  dagre.layout(dagreGraph);

  const layoutedNodes = nodes.map((node) => {
    const nodeWithPosition = dagreGraph.node(node.id);
    return {
      ...node,
      position: {
        x: nodeWithPosition ? nodeWithPosition.x - 125 : 0,
        y: nodeWithPosition ? nodeWithPosition.y - 55 : 0,
      },
    };
  });

  return { nodes: layoutedNodes, edges };
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export default function DependencyGraph({
  repoId,
  onOpenFile,
  selectedFilePath,
}: DependencyGraphProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filter & Toggle controls
  const [includeHidden, setIncludeHidden] = useState(false);
  const [showMoreConnections, setShowMoreConnections] = useState(false);
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set());
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [nodeDetail, setNodeDetail] = useState<NodeDetail | null>(null);
  const [readingOrder, setReadingOrder] = useState<string[]>([]);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const reactFlowWrapper = useRef<HTMLDivElement>(null);

  // Fetch reading order once
  useEffect(() => {
    if (!repoId) return;
    fetchReadingOrder(repoId)
      .then((res) => setReadingOrder(res.reading_order))
      .catch(() => {});
  }, [repoId]);

  // Sync selectedFilePath from parent (e.g. from FileTree)
  useEffect(() => {
    if (selectedFilePath) {
      setSelectedNodeId(selectedFilePath);
    }
  }, [selectedFilePath]);

  // Fetch node detail when a node is selected
  useEffect(() => {
    if (!repoId || !selectedNodeId) {
      setNodeDetail(null);
      return;
    }
    fetchGraphNode(repoId, selectedNodeId)
      .then((detail) => setNodeDetail(detail))
      .catch(() => setNodeDetail(null));
  }, [repoId, selectedNodeId]);

  // Load Overview or Folder data
  const loadGraph = useCallback(async () => {
    if (!repoId) return;
    setLoading(true);
    setError(null);

    try {
      const overview = await fetchGraphOverview(repoId, includeHidden);
      const edgeKinds = showMoreConnections
        ? "import,call,data_read,config_ref,doc_link,test_of"
        : "import";

      // If any folders are expanded, load their files
      let allDisplayNodes: Node[] = [];
      let allDisplayEdges: Edge[] = [];

      // Add folder nodes (unless expanded, or keep both)
      overview.nodes.forEach((fn: FolderNode) => {
        const isExpanded = expandedFolders.has(fn.id);
        const isEntry = overview.entry_points.some((ep) => ep.startsWith(fn.id === "." ? "" : `${fn.id}/`));

        allDisplayNodes.push({
          id: `folder:${fn.id}`,
          type: "custom",
          data: {
            id: fn.id,
            label: fn.label === "." ? "root" : fn.label,
            isFolder: true,
            isExpanded,
            isEntry,
            role: fn.role,
            summary: fn.summary,
            fileCount: fn.file_count,
            loc: fn.loc,
            onToggleFolder: (folderId: string) => {
              setExpandedFolders((prev) => {
                const next = new Set(prev);
                if (next.has(folderId)) next.delete(folderId);
                else next.add(folderId);
                return next;
              });
            },
          },
          position: { x: 0, y: 0 },
        });
      });

      // Folder edges
      overview.edges.forEach((fe: FolderEdge, index: number) => {
        const style = EDGE_STYLES[fe.kind] || EDGE_STYLES.import;
        allDisplayEdges.push({
          id: `fe-${index}`,
          source: `folder:${fe.source}`,
          target: `folder:${fe.target}`,
          style: { stroke: style.stroke, strokeDasharray: style.strokeDasharray, strokeWidth: 2 },
          markerEnd: { type: MarkerType.ArrowClosed, color: style.stroke },
        });
      });

      // For each expanded folder, fetch file-level nodes
      for (const folderId of expandedFolders) {
        try {
          const folderData = await fetchGraphFolder(repoId, folderId, edgeKinds);
          folderData.nodes.forEach((gn: GraphNode) => {
            const isEntry = overview.entry_points.includes(gn.id);
            allDisplayNodes.push({
              id: gn.id,
              type: "custom",
              data: {
                id: gn.id,
                label: gn.label,
                isFolder: false,
                isEntry,
                role: gn.role,
                summary: gn.summary,
                loc: gn.loc,
                onOpenCode: (path: string) => onOpenFile(path),
              },
              position: { x: 0, y: 0 },
            });
          });

          folderData.edges.forEach((ge: GraphEdge, index: number) => {
            const style = EDGE_STYLES[ge.kind] || EDGE_STYLES.import;
            allDisplayEdges.push({
              id: `ge-${folderId}-${index}`,
              source: ge.source,
              target: ge.target,
              style: { stroke: style.stroke, strokeDasharray: style.strokeDasharray, strokeWidth: 1.5 },
              markerEnd: { type: MarkerType.ArrowClosed, color: style.stroke },
            });
          });
        } catch {
          // Folder fetch fallback
        }
      }

      // Compute highlighting: if a node is selected, highlight direct neighbors
      if (selectedNodeId) {
        const directNeighbors = new Set<string>();
        allDisplayEdges.forEach((e) => {
          if (e.source === selectedNodeId) directNeighbors.add(e.target);
          if (e.target === selectedNodeId) directNeighbors.add(e.source);
        });

        allDisplayNodes = allDisplayNodes.map((n) => {
          const nodeId = String((n.data as any)?.id || n.id);
          const isSelected = n.id === selectedNodeId || nodeId === selectedNodeId;
          const isNeighbor = directNeighbors.has(n.id) || directNeighbors.has(nodeId);
          const isDimmed = !isSelected && !isNeighbor;
          return {
            ...n,
            data: { ...n.data, isSelected, isDimmed },
          };
        });
      }

      // Run Dagre layout
      const layouted = layoutElements(allDisplayNodes, allDisplayEdges);
      setNodes(layouted.nodes);
      setEdges(layouted.edges);
      setLoading(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load dependency graph");
      setLoading(false);
    }
  }, [repoId, includeHidden, showMoreConnections, expandedFolders, selectedNodeId, onOpenFile, setNodes, setEdges]);

  useEffect(() => {
    loadGraph();
  }, [loadGraph]);

  // Export diagram to PNG
  async function handleExportPng() {
    if (!reactFlowWrapper.current) return;
    try {
      const dataUrl = await toPng(reactFlowWrapper.current, { backgroundColor: "#ffffff" });
      const link = document.createElement("a");
      link.download = `repo-graph-${repoId}.png`;
      link.href = dataUrl;
      link.click();
    } catch {
      alert("Failed to export PNG");
    }
  }

  return (
    <div className="relative flex flex-col h-[740px] rounded-2xl border border-slate-200/80 bg-white/90 shadow-sm backdrop-blur-md dark:border-slate-800/80 dark:bg-slate-900/90 overflow-hidden">
      {/* Top Controls Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200/80 bg-slate-50/60 p-4 dark:border-slate-800/80 dark:bg-slate-950/40 z-10">
        <div className="flex flex-wrap items-center gap-4 text-xs">
          {/* Legend */}
          <div className="flex items-center gap-2">
            <span className="font-semibold uppercase tracking-wider text-slate-400 text-[10px]">Roles:</span>
            <span className="inline-flex items-center gap-1 font-medium text-emerald-700 dark:text-emerald-300">
              <span className="h-2 w-2 rounded-full bg-emerald-500" /> Entry
            </span>
            <span className="inline-flex items-center gap-1 font-medium text-sky-700 dark:text-sky-300">
              <span className="h-2 w-2 rounded-full bg-sky-500" /> Core
            </span>
            <span className="inline-flex items-center gap-1 font-medium text-amber-700 dark:text-amber-300">
              <span className="h-2 w-2 rounded-full bg-amber-500" /> Helper
            </span>
            <span className="inline-flex items-center gap-1 font-medium text-slate-600 dark:text-slate-400">
              <span className="h-2 w-2 rounded-full bg-slate-400" /> Other
            </span>
          </div>

          <div className="h-4 w-px bg-slate-200 dark:bg-slate-700 hidden sm:block" />

          {/* Toggles */}
          <label className="flex items-center gap-1.5 cursor-pointer text-slate-700 dark:text-slate-300 select-none">
            <input
              type="checkbox"
              checked={showMoreConnections}
              onChange={(e) => setShowMoreConnections(e.target.checked)}
              className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 h-3.5 w-3.5"
            />
            <span>Show more connections</span>
          </label>

          <label className="flex items-center gap-1.5 cursor-pointer text-slate-700 dark:text-slate-300 select-none">
            <input
              type="checkbox"
              checked={includeHidden}
              onChange={(e) => setIncludeHidden(e.target.checked)}
              className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 h-3.5 w-3.5"
            />
            <span>Show tests, configs & docs</span>
          </label>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleExportPng}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 shadow-sm transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
          >
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
            </svg>
            <span>Export PNG</span>
          </button>

          <button
            type="button"
            onClick={() => setShowAdvanced((v) => !v)}
            className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 shadow-sm transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300"
          >
            <span>Advanced</span>
            <svg
              className={`h-3 w-3 transition-transform ${showAdvanced ? "rotate-180" : ""}`}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>
        </div>
      </div>

      {/* Advanced Drawer */}
      {showAdvanced && (
        <div className="border-b border-slate-200 dark:border-slate-800 bg-slate-100/90 dark:bg-slate-950/80 p-4 text-xs text-slate-700 dark:text-slate-300 z-10 space-y-2">
          <div className="flex items-center justify-between">
            <h4 className="font-semibold text-slate-900 dark:text-slate-100">Advanced Graph Analysis</h4>
            <span className="text-[11px] text-slate-400">Deterministic code graph metrics</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="rounded-lg bg-white dark:bg-slate-900 p-2.5 border border-slate-200 dark:border-slate-800">
              <span className="font-semibold text-slate-800 dark:text-slate-200">Total Nodes:</span> {nodes.length}
            </div>
            <div className="rounded-lg bg-white dark:bg-slate-900 p-2.5 border border-slate-200 dark:border-slate-800">
              <span className="font-semibold text-slate-800 dark:text-slate-200">Total Edges:</span> {edges.length}
            </div>
            <div className="rounded-lg bg-white dark:bg-slate-900 p-2.5 border border-slate-200 dark:border-slate-800">
              <span className="font-semibold text-slate-800 dark:text-slate-200">Expanded Folders:</span> {expandedFolders.size}
            </div>
          </div>
        </div>
      )}

      {/* Main Diagram Area */}
      <div className="relative flex-1" ref={reactFlowWrapper}>
        {loading && (
          <div className="absolute inset-0 z-20 flex items-center justify-center bg-white/70 dark:bg-slate-900/70 backdrop-blur-xs">
            <div className="flex items-center gap-3 text-sm text-slate-600 dark:text-slate-300">
              <svg className="h-5 w-5 animate-spin text-indigo-600" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <span>Building dependency diagram…</span>
            </div>
          </div>
        )}

        {error && (
          <div className="absolute inset-0 z-20 flex flex-col items-center justify-center p-6 text-center">
            <p className="text-sm font-semibold text-rose-600 dark:text-rose-400">{error}</p>
            <button
              type="button"
              onClick={loadGraph}
              className="mt-3 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-500"
            >
              Retry
            </button>
          </div>
        )}

        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          nodeTypes={nodeTypes}
          onNodeClick={(_, node) => {
            const path = String((node.data as any)?.id || node.id);
            setSelectedNodeId(path);
          }}
          onPaneClick={() => setSelectedNodeId(null)}
          fitView
          attributionPosition="bottom-left"
        >
          <Background gap={16} size={1} />
          <Controls />
        </ReactFlow>

        {/* "Start Here" Floating Panel */}
        {readingOrder.length > 0 && (
          <div className="absolute bottom-4 left-4 z-10 max-w-xs rounded-xl border border-slate-200/90 bg-white/95 p-3 shadow-lg backdrop-blur-md dark:border-slate-800/90 dark:bg-slate-900/95">
            <div className="flex items-center gap-1.5 mb-2">
              <span className="flex h-5 w-5 items-center justify-center rounded-md bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300 text-[10px] font-bold">
                ★
              </span>
              <h4 className="text-xs font-bold text-slate-800 dark:text-slate-200">Start Here (Reading Order)</h4>
            </div>
            <ol className="space-y-1 text-[11px] font-mono">
              {readingOrder.slice(0, 5).map((path, idx) => (
                <li key={path}>
                  <button
                    type="button"
                    onClick={() => {
                      setSelectedNodeId(path);
                      onOpenFile(path);
                    }}
                    className="flex w-full items-center gap-2 rounded px-1.5 py-0.5 text-left text-slate-700 dark:text-slate-300 hover:bg-indigo-50 dark:hover:bg-indigo-950/60 transition truncate"
                  >
                    <span className="text-[10px] text-slate-400 font-bold">{idx + 1}.</span>
                    <span className="truncate">{path}</span>
                  </button>
                </li>
              ))}
            </ol>
          </div>
        )}

        {/* Side Panel for Selected Node */}
        {nodeDetail && (
          <div className="absolute top-0 right-0 bottom-0 w-80 z-20 border-l border-slate-200 dark:border-slate-800 bg-white/95 dark:bg-slate-900/95 p-4 shadow-xl backdrop-blur-md overflow-y-auto space-y-4">
            <div className="flex items-start justify-between">
              <div>
                <span className={`inline-block rounded px-1.5 py-0.2 text-[9px] font-bold uppercase mb-1 ${
                  ROLE_COLORS[nodeDetail.role]?.badge || ""
                }`}>
                  {nodeDetail.role}
                </span>
                <h3 className="font-mono text-sm font-bold text-slate-900 dark:text-slate-100 break-all">
                  {nodeDetail.path}
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setSelectedNodeId(null)}
                className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
              >
                ✕
              </button>
            </div>

            <p className="text-xs text-slate-600 dark:text-slate-300 leading-relaxed">
              {nodeDetail.summary}
            </p>

            <button
              type="button"
              onClick={() => onOpenFile(nodeDetail.path)}
              className="w-full inline-flex items-center justify-center gap-1.5 rounded-xl bg-indigo-600 px-3 py-2 text-xs font-semibold text-white shadow hover:bg-indigo-500 transition"
            >
              <span>Open Code Viewer</span>
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
              </svg>
            </button>

            {/* Metrics */}
            <div className="grid grid-cols-2 gap-2 text-center text-xs">
              <div className="rounded-lg bg-slate-50 dark:bg-slate-800/60 p-2 border border-slate-100 dark:border-slate-800">
                <div className="text-[10px] text-slate-400">Transitive Dependents</div>
                <div className="font-bold text-slate-800 dark:text-slate-200">{nodeDetail.transitive_dependents_count}</div>
              </div>
              <div className="rounded-lg bg-slate-50 dark:bg-slate-800/60 p-2 border border-slate-100 dark:border-slate-800">
                <div className="text-[10px] text-slate-400">Lines of Code</div>
                <div className="font-bold text-slate-800 dark:text-slate-200">{nodeDetail.loc}</div>
              </div>
            </div>

            {/* This file uses */}
            <div>
              <h4 className="text-xs font-semibold text-slate-800 dark:text-slate-200 mb-1.5">
                This file uses ({nodeDetail.dependencies.length})
              </h4>
              {nodeDetail.dependencies.length > 0 ? (
                <ul className="space-y-1 font-mono text-[11px]">
                  {nodeDetail.dependencies.map((dep) => (
                    <li key={dep}>
                      <button
                        type="button"
                        onClick={() => setSelectedNodeId(dep)}
                        className="text-left text-indigo-600 dark:text-indigo-400 hover:underline truncate w-full"
                      >
                        → {dep}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-[11px] text-slate-400">No internal repo dependencies</p>
              )}
            </div>

            {/* This file is used by */}
            <div>
              <h4 className="text-xs font-semibold text-slate-800 dark:text-slate-200 mb-1.5">
                This file is used by ({nodeDetail.dependents.length})
              </h4>
              {nodeDetail.dependents.length > 0 ? (
                <ul className="space-y-1 font-mono text-[11px]">
                  {nodeDetail.dependents.map((dep) => (
                    <li key={dep}>
                      <button
                        type="button"
                        onClick={() => setSelectedNodeId(dep)}
                        className="text-left text-indigo-600 dark:text-indigo-400 hover:underline truncate w-full"
                      >
                        ← {dep}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-[11px] text-slate-400">No dependents</p>
              )}
            </div>

            {/* Symbols */}
            {nodeDetail.symbols.length > 0 && (
              <div>
                <h4 className="text-xs font-semibold text-slate-800 dark:text-slate-200 mb-1.5">
                  Symbols ({nodeDetail.symbols.length})
                </h4>
                <div className="flex flex-wrap gap-1">
                  {nodeDetail.symbols.slice(0, 10).map((sym) => (
                    <span
                      key={sym.name}
                      onClick={() => onOpenFile(nodeDetail.path, sym.start_line)}
                      className="cursor-pointer rounded bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 font-mono text-[10px] text-slate-700 dark:text-slate-300 hover:bg-indigo-100 hover:text-indigo-700 dark:hover:bg-indigo-950 dark:hover:text-indigo-300"
                      title={`Line ${sym.start_line}-${sym.end_line}`}
                    >
                      {sym.name}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
