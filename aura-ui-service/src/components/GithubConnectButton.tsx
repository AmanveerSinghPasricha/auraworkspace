'use client';

import React from 'react';

interface ConnectButtonProps {
  userId: string;
}

export function GithubConnectButton({ userId }: ConnectButtonProps) {
  const handleConnectGithub = () => {
    const clientId = process.env.NEXT_PUBLIC_GITHUB_CLIENT_ID;
    
    if (!clientId) {
      alert("Please configure NEXT_PUBLIC_GITHUB_CLIENT_ID in .env.local");
      return;
    }

    const redirectUri = encodeURIComponent(`${window.location.origin}/auth/github/callback`);
    const scope = encodeURIComponent('repo user');
    
    // Standard GitHub OAuth URL
    const githubAuthUrl = `https://github.com/login/oauth/authorize?client_id=${clientId}&redirect_uri=${redirectUri}&scope=${scope}&state=${userId}`;
    
    window.location.href = githubAuthUrl;
  };

  return (
    <button
      onClick={handleConnectGithub}
      className="flex items-center gap-2 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-white rounded-md text-xs font-semibold border border-slate-700 transition-colors shadow-sm"
    >
      <span>🐙</span> Connect GitHub
    </button>
  );
}