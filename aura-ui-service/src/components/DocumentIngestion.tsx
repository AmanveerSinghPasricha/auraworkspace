import React, { useState, useRef } from 'react';
import { Upload, FileText, CheckCircle2, AlertCircle, Loader2, X } from 'lucide-react';
import { useAppStore, IngestedDocument } from '../store/useAppStore';

export const DocumentIngestion: React.FC = () => {
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const { activeDocument, setActiveDocument, clearActiveDocument } = useAppStore();

  const handleFileUpload = async (file: File) => {
    setUploading(true);
    setErrorMessage(null);

    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await fetch('http://localhost:8000/api/v1/documents/upload', {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: 'Upload failed' }));
        throw new Error(errorData.detail || 'Failed to process document');
      }

      const data: IngestedDocument = await response.json();
      setActiveDocument(data);
    } catch (err: any) {
      setErrorMessage(err.message || 'Error uploading file.');
    } finally {
      setUploading(false);
    }
  };

  const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      handleFileUpload(e.target.files[0]);
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFileUpload(e.dataTransfer.files[0]);
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col gap-4">
      <h3 className="text-sm font-semibold text-slate-200 flex items-center gap-2">
        <FileText className="w-4 h-4 text-indigo-400" />
        Document Ingestion
      </h3>

      {/* Hidden File Input */}
      <input
        type="file"
        ref={fileInputRef}
        onChange={onFileChange}
        accept=".pdf,.docx,.xlsx,.pptx,.txt"
        className="hidden"
      />

      {/* Active Document Card */}
      {activeDocument ? (
        <div className="bg-indigo-950/40 border border-indigo-500/30 rounded-lg p-3 flex items-center justify-between">
          <div className="flex items-center gap-3 overflow-hidden">
            <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
            <div className="truncate">
              <p className="text-sm font-medium text-slate-100 truncate">{activeDocument.filename}</p>
              <p className="text-xs text-slate-400">
                {activeDocument.chapters_detected} chapter(s) indexed
              </p>
            </div>
          </div>
          <button
            onClick={clearActiveDocument}
            className="p-1 hover:bg-slate-800 text-slate-400 hover:text-slate-200 rounded-md transition"
            title="Detach document"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      ) : (
        /* Upload Dropzone */
        <div
          onClick={() => fileInputRef.current?.click()}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          className={`border-2 border-dashed rounded-lg p-6 flex flex-col items-center justify-center cursor-pointer transition ${
            isDragging
              ? 'border-indigo-500 bg-indigo-500/10'
              : 'border-slate-700 hover:border-slate-500 bg-slate-800/40'
          }`}
        >
          {uploading ? (
            <div className="flex flex-col items-center gap-2 text-slate-400">
              <Loader2 className="w-6 h-6 animate-spin text-indigo-400" />
              <span className="text-xs font-medium">Parsing & Summarizing Tree...</span>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-2 text-center">
              <Upload className="w-6 h-6 text-slate-400" />
              <span className="text-xs font-medium text-slate-300">
                Click or drop documents here
              </span>
              <span className="text-[10px] text-slate-500">
                PDF, TXT, DOCX up to 10MB
              </span>
            </div>
          )}
        </div>
      )}

      {/* Error Banner */}
      {errorMessage && (
        <div className="bg-red-950/50 border border-red-500/30 rounded-lg p-2.5 flex items-center gap-2 text-red-300 text-xs">
          <AlertCircle className="w-4 h-4 shrink-0 text-red-400" />
          <span>{errorMessage}</span>
        </div>
      )}
    </div>
  );
};