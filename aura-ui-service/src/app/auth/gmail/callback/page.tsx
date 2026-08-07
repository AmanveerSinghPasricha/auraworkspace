'use client';

import { useEffect, useRef, Suspense } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';

function GmailCallbackHandler() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const processedRef = useRef(false);

  useEffect(() => {
    if (processedRef.current) return;

    const code = searchParams.get('code');
    const error = searchParams.get('error');

    if (error) {
      console.error('Google OAuth Access Denied:', error);
      router.push('/?error=access_denied');
      return;
    }

    if (code) {
      processedRef.current = true;

      const userId = localStorage.getItem('aura_user_id') || localStorage.getItem('user_id') || '02b7cfb6-f0b2-4d6e-a87b-0b85d4af5fb6';
      const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';
      const redirectUri = `${window.location.origin}/auth/gmail/callback`;

      fetch(`${apiBaseUrl}/api/v1/auth/connect-gmail`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          user_id: userId,
          code: code,
          redirect_uri: redirectUri,
        }),
      })
        .then((res) => {
          if (!res.ok) {
            throw new Error('Code exchange failed');
          }
          return res.json();
        })
        .then(() => {
          router.push('/?connected=gmail');
        })
        .catch((err) => {
          console.error('Gmail connection error:', err);
          router.push('/?error=connection_failed');
        });
    }
  }, [searchParams, router]);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-slate-950 text-white">
      <div className="flex flex-col items-center space-y-4">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-500 border-t-transparent"></div>
        <p className="animate-pulse text-sm font-medium text-slate-300">
          Linking your Gmail account securely...
        </p>
      </div>
    </div>
  );
}

export default function GmailCallbackPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-slate-950 text-white">
          <p className="text-sm text-slate-400">Loading OAuth parameters...</p>
        </div>
      }
    >
      <GmailCallbackHandler />
    </Suspense>
  );
}