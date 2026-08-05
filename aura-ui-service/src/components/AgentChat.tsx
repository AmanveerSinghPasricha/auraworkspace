'use client';

import React, { useState, useRef, useEffect } from 'react';
import { useAppStore } from '../store/useAppStore';
import { api } from '../hooks/useApi';
import { useAuth } from '@/context/AuthContext';
import HitlApprovalModal from './HitlApprovalModal';

export function AgentChat() {
  const { user } = useAuth();
  const [input, setInput] = useState('');
  const [isSending, setIsSending] = useState(false);
  const { messages, addMessage, activeDocument } = useAppStore();
  const chatEndRef = useRef<HTMLDivElement>(null);

  // HITL Modal State
  const [hitlData, setHitlData] = useState<any>(null);
  const [isHitlOpen, setIsHitlOpen] = useState<boolean>(false);
  const [currentThreadId, setCurrentThreadId] = useState<string>('thread_demo_001');

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isSending) return;

    const userText = input.trim();
    setInput('');

    // Safely resolve the logged-in user ID from Auth context
    const activeUserId = 
      user?.id || 
      user?.user_id || 
      user?.email || 
      '02b7cfb6-f0b2-4d6e-a87b-0b85d4af5fb6';

    // Add user message to UI state store
    addMessage({
      id: Date.now().toString(),
      sender: 'user',
      content: userText,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    });

    setIsSending(true);

    try {
      // Document context payload for RAG executions
      const docContext = activeDocument
        ? {
            file_hash: activeDocument.file_hash,
            document_ref: activeDocument.document_ref,
            filename: activeDocument.filename,
          }
        : undefined;

      // Primary chat execution call
      const response = await api.sendMessage(userText, activeUserId, currentThreadId, docContext);

      // Preserve active thread ID returned by gateway
      if (response.thread_id || response.threadId) {
        setCurrentThreadId(response.thread_id || response.threadId);
      }

      // 1. CHECK FOR HITL INTERRUPT SIGNAL FROM LANGGRAPH
      const rawResponseStr = typeof response.response === 'string' ? response.response : '';
      const isInterruptedSignal =
        response.status === 'interrupted' ||
        response.interrupt ||
        response.response?.interrupt ||
        rawResponseStr.includes('__interrupt__') ||
        rawResponseStr.includes('Human authorization required') ||
        rawResponseStr.includes('approval required');

      if (isInterruptedSignal) {
        // Extract staged payload safely
        let interruptPayload = response.interrupt || response.response?.interrupt || response;

        // Parse nested JSON if returned inside a raw text string
        if (typeof interruptPayload === 'string' || rawResponseStr.includes('action_type')) {
          try {
            const jsonMatch = rawResponseStr.match(/\{[\s\S]*\}/);
            if (jsonMatch) {
              interruptPayload = JSON.parse(jsonMatch[0]);
            }
          } catch {
            interruptPayload = {
              action_type: 'send_email',
              recipient: userText.match(/[\w.-]+@[\w.-]+\.\w+/)?.[0] || 'pasrichaamanveer@gmail.com',
              subject: 'Verification Test',
              body: userText,
            };
          }
        }

        setHitlData(interruptPayload);
        setIsHitlOpen(true);

        addMessage({
          id: response.id || (Date.now() + 1).toString(),
          sender: 'assistant',
          content: '⚠️ Action approval required. Please review the pending action in the approval prompt.',
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        });
        return;
      }

      // 2. STANDARD ASSISTANT RESPONSE
      const messageContent =
        response.response || response.content || response.message || 'Response received from AURA agent.';

      addMessage({
        id: response.id || (Date.now() + 1).toString(),
        sender: 'assistant',
        content: messageContent,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        toolCalls: response.toolCalls,
      });
    } catch {
      addMessage({
        id: (Date.now() + 1).toString(),
        sender: 'assistant',
        content: '⚠️ Failed to get response from gateway. Check backend connection.',
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      });
    } finally {
      setIsSending(false);
    }
  };

  // Callback executed when HitlApprovalModal completes the resume action
  const handleHitlCompleted = (resumedResponseText?: string) => {
    addMessage({
      id: (Date.now() + 1).toString(),
      sender: 'assistant',
      content: typeof resumedResponseText === 'string' && resumedResponseText.trim() !== '' 
        ? resumedResponseText 
        : 'Action processed successfully.',
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    });

    // Reset modal state
    setIsHitlOpen(false);
    setHitlData(null);
  };

  return (
    <div className="bg-slate-950/60 border border-slate-800 rounded-xl p-5 flex flex-col h-[650px] relative">
      <h2 className="text-sm font-semibold text-slate-200 mb-4 flex items-center gap-2">
        <span>💬</span> Agent Chat Workspace
      </h2>

      {/* Messages Window */}
      <div className="flex-1 overflow-y-auto space-y-3 pr-2 mb-4">
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-slate-500 text-xs">
            <span>✨ Start a conversation with AURA AI</span>
          </div>
        ) : (
          messages.map((msg) => (
            <div
              key={msg.id}
              className={`flex flex-col ${
                msg.sender === 'user' ? 'items-end' : 'items-start'
              }`}
            >
              <div
                className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-xs ${
                  msg.sender === 'user'
                    ? 'bg-indigo-600 text-white rounded-br-none'
                    : 'bg-slate-900 border border-slate-800 text-slate-200 rounded-bl-none'
                }`}
              >
                <p className="whitespace-pre-wrap">{msg.content}</p>

                {msg.toolCalls && msg.toolCalls.length > 0 && (
                  <div className="mt-2 border-t border-slate-800 pt-2 space-y-1">
                    {msg.toolCalls.map((tool, idx) => (
                      <div key={idx} className="bg-slate-950 p-2 rounded text-[10px] font-mono text-indigo-300">
                        🛠️ Tool: {tool.toolName}
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <span className="text-[10px] text-slate-500 mt-1 px-1">
                {msg.timestamp}
              </span>
            </div>
          ))
        )}
        <div ref={chatEndRef} />
      </div>

      {/* Active Document Context Banner */}
      {activeDocument && (
        <div className="mb-3 px-3 py-1.5 bg-indigo-950/40 border border-indigo-500/30 rounded-lg flex items-center gap-2 text-[11px] text-indigo-300">
          <span className="w-2 h-2 rounded-full bg-indigo-400 animate-pulse"></span>
          <span>RAG Active: <strong>{activeDocument.filename}</strong> ({activeDocument.chapters_detected} chapters)</span>
        </div>
      )}

      {/* Input Box */}
      <form onSubmit={handleSend} className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={
            activeDocument 
              ? `Ask questions about ${activeDocument.filename}...` 
              : "Ask AURA agent or request document analysis..."
          }
          className="flex-1 bg-slate-900 border border-slate-800 rounded-lg px-4 py-2.5 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500 transition-colors"
        />
        <button
          type="submit"
          disabled={isSending || !input.trim()}
          className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-medium text-xs px-5 py-2.5 rounded-lg transition-colors"
        >
          {isSending ? 'Sending...' : 'Send'}
        </button>
      </form>

      {/* HITL Approval Modal Mount */}
      <HitlApprovalModal
        isOpen={isHitlOpen}
        threadId={currentThreadId}
        data={hitlData}
        onClose={(resumedText?: string) => {
          handleHitlCompleted(
            typeof resumedText === 'string' && resumedText.trim() !== '' 
              ? resumedText 
              : 'Action processed successfully.'
          );
        }}
      />
    </div>
  );
}