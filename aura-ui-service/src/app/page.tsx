'use client';

import { useEffect } from 'react';
import { useAppStore } from '../store/useAppStore';
import { api } from '../hooks/useApi';

export default function Home() {
  const { health, setHealth } = useAppStore();

  useEffect(() => {
    async function verifyBackendConnection() {
      try {
        await api.checkHealth();
        setHealth({ status: 'online', gatewayUrl: 'http://localhost:8000' });
      } catch {
        setHealth({ status: 'offline', gatewayUrl: 'http://localhost:8000' });
      }
    }

    verifyBackendConnection();
  }, [setHealth]);

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 flex flex-col font-sans">
      {/* Top Navigation Bar */}
      <header className="border-b border-slate-800 bg-slate-950 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="h-4 w-4 bg-indigo-500 rounded-sm animate-pulse" />
          <h1 className="text-lg font-bold tracking-wide">AURA WORKSPACE</h1>
        </div>

        {/* Gateway Connection Indicator */}
        <div className="flex items-center gap-2 bg-slate-900 border border-slate-800 px-3 py-1.5 rounded-full text-xs">
          <span
            className={`h-2.5 w-2.5 rounded-full ${
              health.status === 'online'
                ? 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]'
                : health.status === 'connecting'
                ? 'bg-amber-500'
                : 'bg-rose-500'
            }`}
          />
          <span className="capitalize font-medium text-slate-300">
            Gateway: {health.status}
          </span>
        </div>
      </header>

      {/* Main Workspace Shell */}
      <main className="flex-1 p-6 max-w-7xl w-full mx-auto grid grid-cols-1 md:grid-cols-3 gap-6">
        <section className="bg-slate-950/50 border border-slate-800 rounded-xl p-5 flex flex-col items-center justify-center text-slate-400 text-sm">
          📁 Document Ingestion Panel
          <span className="text-xs text-slate-500 mt-1">(Coming in Phase 2)</span>
        </section>

        <section className="md:col-span-2 bg-slate-950/50 border border-slate-800 rounded-xl p-5 flex flex-col items-center justify-center text-slate-400 text-sm">
          💬 Agent Chat Workspace
          <span className="text-xs text-slate-500 mt-1">(Coming in Phase 2)</span>
        </section>
      </main>
    </div>
  );
}