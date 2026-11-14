import { useState, useRef, type DragEvent, type ChangeEvent } from "react";
import { uploadDocuments, type DocumentUploadItem } from "../api";

interface PdfUploadCardProps {
  onUploaded: (uploaded: DocumentUploadItem[]) => void;
  disabled?: boolean;
}

const MAX_BYTES_PER_FILE = 20 * 1024 * 1024; // 20 MB
const MAX_FILES = 5;

interface FileValidationState {
  file: File;
  error?: string;
}

export default function PdfUploadCard({ onUploaded, disabled }: PdfUploadCardProps) {
  const [dragActive, setDragActive] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState<FileValidationState[]>([]);
  const [uploading, setUploading] = useState(false);
  const [generalError, setGeneralError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  function validateFiles(incoming: File[]): FileValidationState[] {
    const list = incoming.slice(0, MAX_FILES);
    return list.map((file) => {
      if (!file.name.toLowerCase().endsWith(".pdf") && file.type !== "application/pdf") {
        return { file, error: "Only PDF files (.pdf) are supported" };
      }
      if (file.size > MAX_BYTES_PER_FILE) {
        return { file, error: `Exceeds 20 MB limit (${(file.size / (1024 * 1024)).toFixed(1)} MB)` };
      }
      if (file.size === 0) {
        return { file, error: "File is empty (0 bytes)" };
      }
      return { file };
    });
  }

  function handleDrag(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  }

  function handleDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (disabled || uploading) return;

    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const filesArray = Array.from(e.dataTransfer.files);
      const validated = validateFiles(filesArray);
      setSelectedFiles(validated);
      setGeneralError(null);
    }
  }

  function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    if (e.target.files && e.target.files.length > 0) {
      const filesArray = Array.from(e.target.files);
      const validated = validateFiles(filesArray);
      setSelectedFiles(validated);
      setGeneralError(null);
    }
  }

  async function handleUpload() {
    const valid = selectedFiles.filter((f) => !f.error).map((f) => f.file);
    if (valid.length === 0) {
      setGeneralError("Please select at least one valid PDF file.");
      return;
    }

    setUploading(true);
    setGeneralError(null);
    try {
      const results = await uploadDocuments(valid);
      setSelectedFiles([]);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      onUploaded(results);
    } catch (err) {
      setGeneralError(err instanceof Error ? err.message : "Failed to upload files");
    } finally {
      setUploading(false);
    }
  }

  function handleRemoveFile(index: number) {
    setSelectedFiles((prev) => prev.filter((_, i) => i !== index));
  }

  return (
    <div className="flex h-full flex-col justify-between rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div>
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-100 text-emerald-600 dark:bg-emerald-950/60 dark:text-emerald-400">
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </span>
            <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              Upload PDF documents
            </h2>
          </div>
          <span className="text-[11px] font-medium text-slate-400 dark:text-slate-500">
            Up to 5 files · Max 20MB
          </span>
        </div>

        {/* Drag & Drop Area */}
        <div
          onDragEnter={handleDrag}
          onDragLeave={handleDrag}
          onDragOver={handleDrag}
          onDrop={handleDrop}
          onClick={() => !disabled && !uploading && fileInputRef.current?.click()}
          className={`group relative flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-6 text-center transition ${
            dragActive
              ? "border-emerald-500 bg-emerald-50/50 dark:border-emerald-500 dark:bg-emerald-950/20"
              : "border-slate-300 hover:border-slate-400 dark:border-slate-700 dark:hover:border-slate-600"
          } ${disabled || uploading ? "cursor-not-allowed opacity-60" : ""}`}
        >
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept=".pdf,application/pdf"
            onChange={handleFileChange}
            disabled={disabled || uploading}
            className="hidden"
          />
          <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-full bg-slate-100 text-slate-500 group-hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:group-hover:bg-slate-700">
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
            </svg>
          </div>
          <p className="text-xs font-medium text-slate-700 dark:text-slate-200">
            <span className="text-emerald-600 dark:text-emerald-400 font-semibold">Click to browse</span> or drag & drop PDFs
          </p>
          <p className="mt-1 text-[11px] text-slate-400 dark:text-slate-500">
            Extracted, chunked, and indexed for search and RAG
          </p>
        </div>

        {/* Selected Files List */}
        {selectedFiles.length > 0 && (
          <div className="mt-3 space-y-1.5">
            {selectedFiles.map((item, idx) => (
              <div
                key={idx}
                className="flex items-center justify-between rounded-lg border border-slate-200/80 bg-slate-50/80 px-3 py-1.5 text-xs dark:border-slate-800 dark:bg-slate-800/40"
              >
                <div className="flex items-center gap-2 truncate">
                  <svg className="h-3.5 w-3.5 shrink-0 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
                  </svg>
                  <span className="truncate font-medium text-slate-700 dark:text-slate-200">
                    {item.file.name}
                  </span>
                  <span className="text-[10px] text-slate-400">
                    ({(item.file.size / 1024).toFixed(0)} KB)
                  </span>
                  {item.error && (
                    <span className="rounded bg-rose-100 px-1.5 py-0.5 text-[10px] font-medium text-rose-700 dark:bg-rose-950 dark:text-rose-300">
                      {item.error}
                    </span>
                  )}
                </div>
                {!uploading && (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleRemoveFile(idx);
                    }}
                    className="ml-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                  >
                    ×
                  </button>
                )}
              </div>
            ))}
          </div>
        )}

        {generalError && (
          <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-2 text-xs text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/40 dark:text-rose-300">
            {generalError}
          </div>
        )}
      </div>

      <div className="mt-4 flex items-center justify-end">
        <button
          type="button"
          onClick={handleUpload}
          disabled={disabled || uploading || selectedFiles.length === 0}
          className="inline-flex items-center gap-1.5 rounded-xl bg-emerald-600 px-4 py-2 text-xs font-semibold text-white shadow-sm transition hover:bg-emerald-500 disabled:opacity-50 dark:bg-emerald-500 dark:hover:bg-emerald-400"
        >
          {uploading ? (
            <>
              <svg className="h-3.5 w-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
              <span>Uploading...</span>
            </>
          ) : (
            <span>Upload {selectedFiles.length > 0 ? `(${selectedFiles.length})` : ""}</span>
          )}
        </button>
      </div>
    </div>
  );
}
