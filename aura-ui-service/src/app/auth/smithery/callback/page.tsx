'use client';

import { useEffect, useState, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';

function CallbackContent() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading');
  const [errorMessage, setErrorMessage] = useState('');

  useEffect(() => {
    async function linkConnection() {
      // Extract connection_id and state (user_id) from URL query parameters
      const connectionId = searchParams.get('connection_id');
      const stateUserId = searchParams.get('state');
      
      const activeUserId = stateUserId || localStorage.getItem('aura_user_id');

      if (!connectionId) {
        setStatus('error');
        setErrorMessage('Missing connection_id parameter in OAuth response.');
        return;
      }

      if (!activeUserId) {
        setStatus('error');
        setErrorMessage('User session not found. Please log in to Aura Workspace.');
        return;
      }

      try {
        // Send connection ID to FastAPI backend
        const response = await fetch('http://localhost:8000/api/v1/auth/connect-smithery', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            user_id: activeUserId,
            smithery_connection_id: connectionId,
          }),
        });

        if (!response.ok) {
          const errData = await response.json();
          throw new Error(errData.detail || 'Failed to save Smithery connection.');
        }

        setStatus('success');
        setTimeout(() => {
          router.push('/');
        }, 1500);
      } catch (err: any) {
        setStatus('error');
        setErrorMessage(err.message || 'An unexpected error occurred during account linking.');
      }
    }

    linkConnection();
  }, [searchParams, router]);

  return (
    <div className="bg-slate-900 border border-slate-800 p-8 rounded-xl max-w-md w-full text-center space-y-4 shadow-xl">
      {status === 'loading' && (
        <>
          <div className="w-10 h-10 border-4 border-red-500 border-t-transparent rounded-full animate-spin mx-auto" />
          <h2 className="text-lg font-semibold text-slate-100">Linking Gmail Account...</h2>
          <p className="text-xs text-slate-400">Saving your Smithery connection credentials to Aura Workspace.</p>
        </>
      )}

      {status === 'success' && (
        <>
          <div className="text-4xl">✅</div>
          <h2 className="text-lg font-semibold text-emerald-400">Gmail Account Linked!</h2>
          <p className="text-xs text-slate-400">Redirecting to your workspace...</p>
        </>
      )}

      {status === 'error' && (
        <>
          <div className="text-4xl">❌</div>
          <h2 className="text-lg font-semibold text-rose-500">Connection Failed</h2>
          <p className="text-xs text-slate-400">{errorMessage}</p>
          <button
            onClick={() => router.push('/')}
            className="mt-4 px-4 py-2 bg-slate-800 hover:bg-slate-700 text-xs font-medium rounded-md text-slate-200 transition-colors"
          >
            Return to Workspace
          </button>
        </>
      )}
    </div>
  );
}

export default function SmitheryCallbackPage() {
  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center p-4 font-sans">
      <Suspense fallback={<div className="text-slate-400 text-sm">Processing OAuth callback...</div>}>
        <CallbackContent />
      </Suspense>
    </div>
  );
}