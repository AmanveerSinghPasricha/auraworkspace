'use client';

import React, { useState } from 'react';

interface HitlApprovalModalProps {
  isOpen: boolean;
  threadId: string;
  data: any;
  onClose: (resumedText?: string) => void;
}

export default function HitlApprovalModal({
  isOpen,
  threadId,
  data,
  onClose,
}: HitlApprovalModalProps) {
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!isOpen || !data) return null;

  const handleApprove = async () => {
    setIsSubmitting(true);
    try {
      const BASE_HOST =
        process.env.NEXT_PUBLIC_API_BASE_URL ||
        process.env.NEXT_PUBLIC_API_URL ||
        "http://127.0.0.1:8000";

      const API_BASE_URL = BASE_HOST.endsWith("/api/v1")
        ? BASE_HOST
        : `${BASE_HOST.replace(/\/$/, "")}/api/v1`;

      const token = typeof window !== "undefined" ? localStorage.getItem("aura_token") : null;
      const storedUserId = typeof window !== "undefined" ? localStorage.getItem("aura_user_id") : null;
      const resolvedUserId = storedUserId || "02b7cfb6-f0b2-4d6e-a87b-0b85d4af5fb6";

      // Direct, standalone API request to resume workflow
      const response = await fetch(`${API_BASE_URL}/chat/resume`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          "X-User-ID": resolvedUserId,
        },
        body: JSON.stringify({
          thread_id: threadId || "thread_demo_001",
          resume_payload: {
            approved: true,
            user_id: resolvedUserId,
          },
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `Server error: ${response.status}`);
      }

      const res = await response.json();
      const responseText = res?.response || res?.message || '✅ Action processed successfully.';

      onClose(responseText);
    } catch (err: any) {
      console.error('Modal resume execution failed:', err);
      onClose(
        typeof err?.message === 'string'
          ? `❌ Error: ${err.message}`
          : '❌ Failed to complete action. Gateway error.'
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleReject = async () => {
    setIsSubmitting(true);
    try {
      const BASE_HOST =
        process.env.NEXT_PUBLIC_API_BASE_URL ||
        process.env.NEXT_PUBLIC_API_URL ||
        "http://127.0.0.1:8000";

      const API_BASE_URL = BASE_HOST.endsWith("/api/v1")
        ? BASE_HOST
        : `${BASE_HOST.replace(/\/$/, "")}/api/v1`;

      const token = typeof window !== "undefined" ? localStorage.getItem("aura_token") : null;

      await fetch(`${API_BASE_URL}/chat/resume`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          thread_id: threadId || "thread_demo_001",
          resume_payload: {
            approved: false,
          },
        }),
      });

      onClose('Email action was cancelled by user.');
    } catch {
      onClose('Email action was cancelled by user.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 max-w-md w-full shadow-2xl space-y-4">
        <div className="flex items-center gap-2 text-amber-400 font-semibold text-sm">
          <span>⚠️</span> Action Authorization Required
        </div>

        <p className="text-xs text-slate-300">
          The agent is requesting approval to perform the following action:
        </p>

        {/* Staged Action Details */}
        <div className="bg-slate-950 p-3.5 rounded-xl border border-slate-800/80 space-y-2 text-xs font-mono">
          <div>
            <span className="text-slate-500">Action:</span>{' '}
            <span className="text-indigo-400 font-semibold">
              {data.action_type || 'send_email'}
            </span>
          </div>
          {data.recipient && (
            <div>
              <span className="text-slate-500">To:</span>{' '}
              <span className="text-slate-200">{data.recipient}</span>
            </div>
          )}
          {data.subject && (
            <div>
              <span className="text-slate-500">Subject:</span>{' '}
              <span className="text-slate-200">{data.subject}</span>
            </div>
          )}
          {data.body && (
            <div>
              <span className="text-slate-500">Body:</span>
              <p className="text-slate-300 font-sans mt-1 p-2 bg-slate-900 rounded border border-slate-800/50 whitespace-pre-wrap max-h-32 overflow-y-auto">
                {data.body}
              </p>
            </div>
          )}
        </div>

        {/* Action Buttons */}
        <div className="flex justify-end gap-3 pt-2">
          <button
            type="button"
            onClick={handleReject}
            disabled={isSubmitting}
            className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleApprove}
            disabled={isSubmitting}
            className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition-colors disabled:opacity-50 flex items-center gap-1.5"
          >
            {isSubmitting ? 'Dispatching...' : 'Approve & Send'}
          </button>
        </div>
      </div>
    </div>
  );
}