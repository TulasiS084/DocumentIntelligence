import { FormEvent, useState } from "react";
import { isValidGithubUrl } from "../api";

interface UrlFormProps {
  disabled?: boolean;
  onSubmitUrl: (url: string) => Promise<void>;
}

const SAMPLE_REPOS = [
  "https://github.com/octocat/Hello-World",
  "https://github.com/pallets/flask",
  "https://github.com/expressjs/express",
];

export default function UrlForm({ disabled, onSubmitUrl }: UrlFormProps) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = url.trim();
    if (!trimmed) {
      setError("Please enter a GitHub repository URL.");
      return;
    }
    if (!isValidGithubUrl(trimmed)) {
      setError(
        "Invalid format. Please enter a public GitHub URL like https://github.com/owner/repo (no query, fragments, or extra segments).",
      );
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      await onSubmitUrl(trimmed);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start analysis");
    } finally {
      setSubmitting(false);
    }
  }

  function handleSelectSample(sampleUrl: string) {
    if (disabled || submitting) return;
    setUrl(sampleUrl);
    setError(null);
  }

  const isBusy = disabled || submitting;

  return (
    <div className="rounded-2xl border border-slate-200/80 bg-white/80 p-6 shadow-sm backdrop-blur-md dark:border-slate-800/80 dark:bg-slate-900/80">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label
            htmlFor="repo-url-input"
            className="flex items-center justify-between text-sm font-medium text-slate-700 dark:text-slate-300"
          >
            <span>Public GitHub Repository URL</span>
            <span className="text-xs text-slate-400">Step 1: Shallow Clone & Scan</span>
          </label>

          <div className="mt-2 flex flex-col gap-2 sm:flex-row">
            <div className="relative flex-1">
              <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3.5 text-slate-400">
                <svg
                  className="h-5 w-5"
                  fill="currentColor"
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                >
                  <path
                    fillRule="evenodd"
                    clipRule="evenodd"
                    d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"
                  />
                </svg>
              </div>

              <input
                id="repo-url-input"
                name="url"
                type="text"
                autoComplete="off"
                spellCheck="false"
                placeholder="https://github.com/owner/repository"
                value={url}
                disabled={isBusy}
                onChange={(event) => {
                  setUrl(event.target.value);
                  if (error) setError(null);
                }}
                className="w-full rounded-xl border border-slate-300 bg-white/90 py-2.5 pl-11 pr-10 text-sm font-medium text-slate-900 shadow-sm transition placeholder:text-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700 dark:bg-slate-950/90 dark:text-slate-100 dark:focus:border-indigo-400 dark:focus:ring-indigo-400/20"
              />

              {url && !isBusy && (
                <button
                  type="button"
                  onClick={() => {
                    setUrl("");
                    setError(null);
                  }}
                  className="absolute inset-y-0 right-0 flex items-center pr-3 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                  title="Clear input"
                >
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              )}
            </div>

            <button
              id="submit-repo-button"
              type="submit"
              disabled={isBusy}
              className="inline-flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-indigo-600 to-indigo-700 px-5 py-2.5 text-sm font-semibold text-white shadow-md shadow-indigo-500/20 transition hover:from-indigo-500 hover:to-indigo-600 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60 dark:from-indigo-500 dark:to-indigo-600 dark:hover:from-indigo-400 dark:hover:to-indigo-500"
            >
              {submitting ? (
                <>
                  <svg
                    className="h-4 w-4 animate-spin text-white"
                    xmlns="http://www.w3.org/2000/svg"
                    fill="none"
                    viewBox="0 0 24 24"
                  >
                    <circle
                      className="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                    />
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                    />
                  </svg>
                  <span>Queueing…</span>
                </>
              ) : (
                <>
                  <span>Analyze</span>
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
                  </svg>
                </>
              )}
            </button>
          </div>
        </div>

        {error && (
          <div
            id="url-form-error"
            role="alert"
            className="flex items-start gap-2.5 rounded-xl border border-rose-200 bg-rose-50/80 p-3 text-sm text-rose-700 dark:border-rose-900/50 dark:bg-rose-950/50 dark:text-rose-300"
          >
            <svg className="mt-0.5 h-4 w-4 shrink-0 text-rose-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <p className="flex-1 font-medium">{error}</p>
          </div>
        )}

        <div className="flex flex-wrap items-center justify-between gap-2 pt-1 text-xs text-slate-500 dark:text-slate-400">
          <div className="flex flex-wrap items-center gap-1.5">
            <span>Try sample:</span>
            {SAMPLE_REPOS.map((sample) => {
              const name = sample.replace("https://github.com/", "");
              return (
                <button
                  key={sample}
                  type="button"
                  disabled={isBusy}
                  onClick={() => handleSelectSample(sample)}
                  className="rounded-md border border-slate-200 bg-slate-100/70 px-2 py-0.5 font-mono text-[11px] text-slate-700 transition hover:bg-slate-200 hover:text-slate-900 disabled:opacity-50 dark:border-slate-700/80 dark:bg-slate-800/60 dark:text-slate-300 dark:hover:bg-slate-700 dark:hover:text-white"
                >
                  {name}
                </button>
              );
            })}
          </div>

          <div className="flex items-center gap-1 text-[11px] text-slate-400">
            <svg className="h-3.5 w-3.5 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
            </svg>
            <span>Safe sandbox: depth=1 shallow clone, 300MB cap, auto-cleanup</span>
          </div>
        </div>
      </form>
    </div>
  );
}
