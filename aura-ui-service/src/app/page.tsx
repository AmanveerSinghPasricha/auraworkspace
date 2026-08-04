'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/context/AuthContext';
import { useAppStore } from '../store/useAppStore';
import { api } from '../hooks/useApi';
import { DocumentUpload } from '../components/DocumentUpload';
import { AgentChat } from '../components/AgentChat';
import { GithubConnectButton } from '../components/GithubConnectButton';

export default function Home() {
  const { user, isLoading, logout } = useAuth();
  const router = useRouter();
  const { health, setHealth } = useAppStore();

  // Redirect to /login if the user is not authenticated
  useEffect(() => {
    if (!isLoading && !user) {
      router.push('/login');
    }
  }, [user, isLoading, router]);

  // Check backend health on component mount
  useEffect(() => {
    let isMounted = true;

    async function verifyBackendConnection() {
      try {
        await api.checkHealth();
        if (isMounted) {
          setHealth({ status: 'online', gatewayUrl: 'http://localhost:8000' });
        }
      } catch {
        if (isMounted) {
          setHealth({ status: 'offline', gatewayUrl: 'http://localhost:8000' });
        }
      }
    }

    verifyBackendConnection();

    return () => {
      isMounted = false;
    };
  }, [setHealth]);

  if (isLoading || !user) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center text-slate-400 text-sm">
        Loading workspace...
      </div>
    );
  }

  // Safe fallback to resolve the active user UUID
  const activeUserId = user.id || user.user_id || '02b7cfb6-f0b2-4d6e-a87b-0b85d4af5fb6';

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 flex flex-col font-sans">
      {/* Header */}
      <header className="border-b border-slate-800 bg-slate-950 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="h-4 w-4 bg-indigo-500 rounded-sm animate-pulse" />
          <h1 className="text-lg font-bold tracking-wide">AURA WORKSPACE</h1>
        </div>

        <div className="flex items-center gap-4">
          {/* Health Indicator */}
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

          {/* Single, Official GitHub OAuth Connection Button */}
          <GithubConnectButton userId={activeUserId} />

          {/* User Profile & Logout */}
          <div className="flex items-center gap-3 border-l border-slate-800 pl-4">
            <span className="text-xs text-slate-400 hidden sm:inline">
              {user.email || 'Authenticated'}
            </span>
            <button
              onClick={logout}
              className="text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 px-3 py-1.5 rounded-md transition-colors"
            >
              Logout
            </button>
          </div>
        </div>
      </header>

      {/* Workspace Grid */}
      <main className="flex-1 p-6 max-w-7xl w-full mx-auto grid grid-cols-1 md:grid-cols-3 gap-6">
        <section className="md:col-span-1">
          <DocumentUpload />
        </section>

        <section className="md:col-span-2">
          <AgentChat />
        </section>
      </main>
    </div>
  );
}