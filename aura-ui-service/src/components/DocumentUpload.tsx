'use client';

import React, { useState, useRef } from 'react';
import { useAppStore } from '../store/useAppStore';
import { api } from '../hooks/useApi';

export function DocumentUpload() {
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { documents, addDocument, updateDocumentStatus } = useAppStore();

  const handleFileUpload = async (file: File) => {
    const tempId = Date.now().toString();
    addDocument({
      id: tempId,
      filename: file.name,
      status: 'uploading',
      progress: 25,
    });

    try {
      const formData = new FormData();
      formData.append('file', file);

      updateDocumentStatus(tempId, { progress: 60, status: 'processing' });
      const result = await api.uploadDocument(formData);

      updateDocumentStatus(tempId, {
        id: result.id || tempId,
        status: 'completed',
        progress: 100,
      });
    } catch (err) {
      updateDocumentStatus(tempId, {
        status: 'failed',
        error: err instanceof Error ? err.message : 'Upload failed',
      });
    }
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files?.[0]) {
      handleFileUpload(e.dataTransfer.files[0]);
    }
  };

  return (
    <div className="bg-slate-950/60 border border-slate-800 rounded-xl p-5 flex flex-col h-full">
      <h2 className="text-sm font-semibold text-slate-200 mb-4 flex items-center gap-2">
        <span>📁</span> Document Ingestion
      </h2>

      {/* Drag and Drop Zone */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={onDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`border-2 border-dashed rounded-lg p-6 flex flex-col items-center justify-center cursor-pointer transition-colors ${
          isDragging
            ? 'border-indigo-500 bg-indigo-500/10'
            : 'border-slate-700 hover:border-slate-600 bg-slate-900/40'
        }`}
      >
        <input
          type="file"
          ref={fileInputRef}
          className="hidden"
          onChange={(e) => e.target.files?.[0] && handleFileUpload(e.target.files[0])}
        />
        <span className="text-2xl mb-2">📄</span>
        <p className="text-xs text-slate-300 font-medium text-center">
          Click or drop documents here
        </p>
        <p className="text-[10px] text-slate-500 mt-1">PDF, TXT, DOCX up to 10MB</p>
      </div>

      {/* Uploaded Documents List */}
      <div className="mt-4 flex-1 overflow-y-auto space-y-2 pr-1">
        {documents.map((doc) => (
          <div
            key={doc.id}
            className="bg-slate-900 border border-slate-800 p-3 rounded-lg text-xs flex flex-col gap-1.5"
          >
            <div className="flex items-center justify-between font-medium text-slate-200">
              <span className="truncate max-w-[180px]">{doc.filename}</span>
              <span
                className={`text-[10px] px-2 py-0.5 rounded-full capitalize ${
                  doc.status === 'completed'
                    ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                    : doc.status === 'failed'
                    ? 'bg-rose-950 text-rose-400 border border-rose-800'
                    : 'bg-amber-950 text-amber-400 border border-amber-800'
                }`}
              >
                {doc.status}
              </span>
            </div>
            {doc.status !== 'completed' && doc.status !== 'failed' && (
              <div className="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
                <div
                  className="bg-indigo-500 h-full transition-all duration-300"
                  style={{ width: `${doc.progress}%` }}
                />
              </div>
            )}
            {doc.error && <p className="text-[10px] text-rose-400">{doc.error}</p>}
          </div>
        ))}
      </div>
    </div>
  );
}