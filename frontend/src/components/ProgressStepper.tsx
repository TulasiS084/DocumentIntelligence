import { useEffect, useState } from "react";
import type { PipelineStatus } from "../api";

interface ProgressStepperProps {
  status: PipelineStatus | null;
  error: string | null;
}

type StepId = "cloning" | "scanning" | "parsing" | "graphing" | "ready";

interface StepConfig {
  id: StepId;
  label: string;
  description: string;
}

const STEPS: StepConfig[] = [
  {
    id: "cloning",
    label: "Cloning",
    description: "Shallow clone (depth 1) into isolated sandbox",
  },
  {
    id: "scanning",
    label: "Scanning",
    description: "Walking repository, detecting languages & counting LOC",
  },
  {
    id: "parsing",
    label: "Parsing",
    description: "Extracting imports, symbols & references with tree-sitter",
  },
  {
    id: "graphing",
    label: "Graphing",
    description: "Building file connection graph & folder aggregations",
  },
  {
    id: "ready",
    label: "Ready",
    description: "Code, graph & metadata ready to inspect",
  },
];

const STAGE_ORDER: StepId[] = ["cloning", "scanning", "parsing", "graphing", "ready"];

export default function ProgressStepper({ status, error }: ProgressStepperProps) {
  const [lastActiveStage, setLastActiveStage] = useState<StepId>("cloning");

  useEffect(() => {
    if (status && status !== "failed" && status !== "ready") {
      setLastActiveStage(status);
    }
  }, [status]);

  function getStepState(stepId: StepId) {
    if (!status) return "pending";

    const currentStageIndex = status === "failed" 
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

  const isWorking = status === "cloning" || status === "scanning" || status === "parsing" || status === "graphing";

  return (
    <div
      id="progress-stepper"
      className="rounded-2xl border border-slate-200/80 bg-white/90 p-6 shadow-sm backdrop-blur-md dark:border-slate-800/80 dark:bg-slate-900/90"
    >
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
          Analysis Pipeline Progress
        </h2>
        {status && (
          <span
            className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${
              status === "ready"
                ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300"
                : status === "failed"
                  ? "bg-rose-50 text-rose-700 dark:bg-rose-950/60 dark:text-rose-300"
                  : "bg-indigo-50 text-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-300"
            }`}
          >
            {isWorking ? (
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-indigo-500" />
            ) : null}
            Status: {status}
          </span>
        )}
      </div>

      <ol className="relative flex flex-col gap-4 sm:flex-row sm:items-start sm:gap-2">
        {STEPS.map((step, index) => {
          const state = getStepState(step.id);
          const isLast = index === STEPS.length - 1;

          return (
            <li key={step.id} className="relative flex flex-1 items-start gap-3 sm:flex-col sm:gap-2">
              <div className="flex w-full items-center">
                {/* Step Circle Indicator */}
                <div
                  className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-xs font-bold transition-all duration-300 ${
                    state === "done"
                      ? "bg-emerald-600 text-white shadow-sm shadow-emerald-500/30"
                      : state === "active"
                        ? "bg-indigo-600 text-white shadow-md shadow-indigo-500/40 ring-4 ring-indigo-100 dark:ring-indigo-950"
                        : state === "failed"
                          ? "bg-rose-600 text-white shadow-md shadow-rose-500/30 ring-4 ring-rose-100 dark:ring-rose-950"
                          : "border border-slate-200 bg-slate-100 text-slate-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400"
                  }`}
                >
                  {state === "done" ? (
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                    </svg>
                  ) : state === "active" ? (
                    <svg className="h-4 w-4 animate-spin text-white" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                  ) : state === "failed" ? (
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  ) : (
                    <span>{index + 1}</span>
                  )}
                </div>

                {/* Connecting Line (for desktop) */}
                {!isLast && (
                  <div
                    className={`hidden h-0.5 flex-1 transition-colors duration-300 sm:mx-2 sm:block ${
                      state === "done"
                        ? "bg-emerald-500"
                        : "bg-slate-200 dark:bg-slate-700"
                    }`}
                  />
                )}
              </div>

              {/* Step Labels */}
              <div className="flex-1 sm:pt-1">
                <div className="flex items-center gap-1.5">
                  <h3
                    className={`text-sm font-semibold ${
                      state === "active"
                        ? "text-indigo-600 dark:text-indigo-400"
                        : state === "done"
                          ? "text-slate-900 dark:text-slate-100"
                          : state === "failed"
                            ? "text-rose-600 dark:text-rose-400"
                            : "text-slate-500 dark:text-slate-400"
                    }`}
                  >
                    {step.label}
                  </h3>
                  {state === "active" && (
                    <span className="flex h-2 w-2 rounded-full bg-indigo-600 animate-ping" />
                  )}
                </div>
                <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
                  {step.description}
                </p>
              </div>
            </li>
          );
        })}
      </ol>

      {/* Failure Alert Box */}
      {status === "failed" && (
        <div
          id="stepper-error-alert"
          role="alert"
          className="mt-5 flex items-start gap-3 rounded-xl border border-rose-200 bg-rose-50/90 p-4 text-sm text-rose-800 dark:border-rose-900/60 dark:bg-rose-950/60 dark:text-rose-200"
        >
          <div className="rounded-lg bg-rose-100 p-1.5 dark:bg-rose-900/50">
            <svg className="h-5 w-5 text-rose-600 dark:text-rose-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          </div>
          <div>
            <h4 className="font-semibold text-rose-900 dark:text-rose-100">Analysis Failed</h4>
            <p className="mt-0.5 text-rose-700 dark:text-rose-300">
              {error || "An unexpected error occurred during repository analysis."}
            </p>
            <p className="mt-2 text-xs text-rose-600/80 dark:text-rose-400/80">
              Temporary clone directory was safely cleaned up. Verify the URL is public and valid, then try again.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
