'use client';

import { useEffect, useState } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';

export default function GithubCallbackPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const [status, setStatus] = useState('Exchanging code for token...');

  useEffect(() => {
    const code = searchParams.get('code');
    const userId = searchParams.get('state');

    if (!code || !userId) {
      setStatus('❌ Missing code or state from GitHub callback.');
      return;
    }

    // Exchange code with FastAPI backend
    fetch('http://localhost:8000/api/v1/auth/connect-github', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        code,
        user_id: userId,
      }),
    })
      .then((res) => {
        if (!res.ok) throw new Error('Failed to connect GitHub account');
        return res.json();
      })
      .then(() => {
        setStatus('✅ GitHub account successfully connected! Redirecting...');
        setTimeout(() => router.push('/'), 2000);
      })
      .catch((err) => {
        setStatus(`❌ Error: ${err.message}`);
      });
  }, [searchParams, router]);

  return (
    <div className="min-h-screen bg-slate-950 text-white flex items-center justify-center p-4">
      <div className="bg-slate-900 border border-slate-800 p-8 rounded-lg shadow-xl text-center max-w-md w-full">
        <h2 className="text-xl font-bold mb-4">GitHub Authorization</h2>
        <p className="text-sm text-slate-300">{status}</p>
      </div>
    </div>
  );
}