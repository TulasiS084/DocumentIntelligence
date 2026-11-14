import { useEffect, useState } from "react";
import type { DocPipelineStatus } from "../api";

interface DocumentProgressStepperProps {
  status: DocPipelineStatus | null;
  error: string | null;
}

type StepId =
  | "uploading"
  | "extracting"
  | "chunking"
  | "indexing"
  | "summarizing"
  | "ready";

interface StepConfig {
  id: StepId;
  label: string;
  description: string;
}

const STEPS: StepConfig[] = [
  {
    id: "uploading",
    label: "Uploading",
    description: "Streaming bytes & verifying PDF integrity",
  },
  {
    id: "extracting",
    label: "Extracting",
    description: "Extracting pages, tables & bookmarks with pdfplumber",
  },
  {
    id: "chunking",
    label: "Chunking",
    description: "Grouping by page boundaries & formatting context",
  },
  {
    id: "indexing",
    label: "Indexing",
    description: "Generating embeddings & building BM25 index",
  },
  {
    id: "summarizing",
    label: "Summarizing",
    description: "Generating executive overview & suggested questions",
  },
  {
    id: "ready",
    label: "Ready",
    description: "Document outline, pages & search ready to inspect",
  },
];

const STAGE_ORDER: StepId[] = [
  "uploading",
  "extracting",
  "chunking",
  "indexing",
  "summarizing",
  "ready",
];

export default function DocumentProgressStepper({ status, error }: DocumentProgressStepperProps) {
  const [lastActiveStage, setLastActiveStage] = useState<StepId>("uploading");

  useEffect(() => {
    if (status && status !== "failed" && status !== "ready") {
      setLastActiveStage(status);
    }
  }, [status]);

  function getStepState(stepId: StepId) {
    if (!status) return "pending";

    const currentStageIndex =
      status === "failed"
        ? STAGE_ORDER.indexOf(lastActiveStage)
        : STAGE_ORDER.indexOf(status);

    const thisStepIndex = STAGE_ORDER.indexOf(stepId);

    if (status === "failed") {
      if (thisStepIndex === currentStageIndex) return "failed";
      if (thisStepIndex < currentStageIndex) return "done";
      return "pending";
    }

    if (status === "ready") return "done";
    if (thisStepIndex < currentStageIndex) return "done";
    if (thisStepIndex === currentStageIndex) return "active";
    return "pending";
  }

  return (
    <div className="mb-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="mb-4 flex items-center justify-between border-b border-slate-100 pb-3 dark:border-slate-800">
        <div>
          <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            Document Ingestion Progress
          </h2>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Status: <span className="font-medium text-slate-700 dark:text-slate-300">{status ?? "idle"}</span>
          </p>
        </div>
        {status && status !== "ready" && status !== "failed" && (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-medium text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
            Processing
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {STEPS.map((step, idx) => {
          const state = getStepState(step.id);
          return (
            <div
              key={step.id}
              className={`relative flex flex-col justify-between rounded-xl border p-3 transition ${
                state === "active"
                  ? "border-emerald-500 bg-emerald-50/50 dark:border-emerald-500/80 dark:bg-emerald-950/20"
                  : state === "done"
                  ? "border-slate-200 bg-slate-50/60 dark:border-slate-800 dark:bg-slate-800/40"
                  : state === "failed"
                  ? "border-rose-300 bg-rose-50 dark:border-rose-900/60 dark:bg-rose-950/30"
                  : "border-slate-100 bg-white opacity-60 dark:border-slate-800/60 dark:bg-slate-900"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-semibold text-slate-400">0{idx + 1}</span>
                {state === "done" ? (
                  <span className="flex h-4 w-4 items-center justify-center rounded-full bg-emerald-500 text-white">
                    <svg className="h-2.5 w-2.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                    </svg>
                  </span>
                ) : state === "active" ? (
                  <span className="h-2 w-2 animate-ping rounded-full bg-emerald-500" />
                ) : state === "failed" ? (
                  <span className="flex h-4 w-4 items-center justify-center rounded-full bg-rose-500 text-white font-bold text-[10px]">
                    !
                  </span>
                ) : null}
              </div>
              <div className="mt-2">
                <div className="text-xs font-semibold text-slate-800 dark:text-slate-200">
                  {step.label}
                </div>
                <div className="mt-0.5 line-clamp-2 text-[10px] text-slate-500 dark:text-slate-400">
                  {step.description}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {status === "failed" && (
        <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/40 dark:text-rose-300">
          <div className="font-semibold">Document Processing Failed</div>
          <div className="mt-1">{error || "An unknown error occurred during PDF parsing."}</div>
        </div>
      )}
    </div>
  );
}
