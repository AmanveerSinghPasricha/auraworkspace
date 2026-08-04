"use client";

import React, { useState } from "react";

interface HitlInterruptData {
  action_type: string;
  recipient: string;
  subject: string;
  body: string;
  message?: string;
}

interface HitlApprovalModalProps {
  isOpen: boolean;
  threadId: string;
  data: HitlInterruptData | null;
  apiBaseUrl?: string;
  onClose: () => void;
}

export const HitlApprovalModal: React.FC<HitlApprovalModalProps> = ({
  isOpen,
  threadId,
  data,
  apiBaseUrl = "http://localhost:8000",
  onClose,
}) => {
  const [submitting, setSubmitting] = useState<boolean>(false);

  if (!isOpen || !data) return null;

  const handleDecision = async (approved: boolean) => {
    try {
      setSubmitting(true);
      const response = await fetch(`${apiBaseUrl}/api/v1/chat/resume`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          thread_id: threadId,
          resume_payload: { approved },
        }),
      });

      if (!response.ok) {
        throw new Error("Failed to resume execution.");
      }

      onClose();
    } catch (err) {
      console.error("HITL resume error:", err);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-lg rounded-xl bg-white p-6 shadow-2xl border border-gray-200 dark:bg-slate-900 dark:border-slate-800">
        <div className="flex items-center justify-between border-b pb-3 border-gray-100 dark:border-slate-800">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-2">
            ⚠️ Action Approval Required
          </h3>
          <span className="text-xs uppercase px-2 py-1 bg-amber-100 text-amber-800 rounded font-bold dark:bg-amber-900/40 dark:text-amber-300">
            {data.action_type}
          </span>
        </div>

        <div className="mt-4 space-y-3 text-sm text-gray-700 dark:text-slate-300">
          <div>
            <span className="font-semibold block text-xs uppercase text-gray-400">To:</span>
            <p className="p-2 bg-gray-50 rounded dark:bg-slate-800 font-mono text-xs">{data.recipient}</p>
          </div>

          <div>
            <span className="font-semibold block text-xs uppercase text-gray-400">Subject:</span>
            <p className="p-2 bg-gray-50 rounded dark:bg-slate-800 font-medium">{data.subject}</p>
          </div>

          <div>
            <span className="font-semibold block text-xs uppercase text-gray-400">Body Preview:</span>
            <div className="p-3 bg-gray-50 rounded dark:bg-slate-800 max-h-40 overflow-y-auto whitespace-pre-wrap text-xs">
              {data.body}
            </div>
          </div>
        </div>

        <div className="mt-6 flex justify-end gap-3 pt-3 border-t border-gray-100 dark:border-slate-800">
          <button
            onClick={() => handleDecision(false)}
            disabled={submitting}
            className="px-4 py-2 text-sm font-medium rounded-lg text-gray-700 bg-gray-100 hover:bg-gray-200 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
          >
            Reject
          </button>
          <button
            onClick={() => handleDecision(true)}
            disabled={submitting}
            className="px-4 py-2 text-sm font-medium rounded-lg text-white bg-green-600 hover:bg-green-700 disabled:opacity-50"
          >
            {submitting ? "Sending..." : "Approve & Send"}
          </button>
        </div>
      </div>
    </div>
  );
};

export default HitlApprovalModal;