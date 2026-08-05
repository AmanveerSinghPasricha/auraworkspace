'use client';

import React from 'react';
import { GithubConnectButton } from '@/components/GithubConnectButton';
import { ConnectGmailButton } from '@/components/ConnectGmailButton';

interface HeaderProps {
  userId?: string;
  userEmail?: string;
}

export function Header({ userId, userEmail }: HeaderProps) {
  // Fallback to default demo user ID if not logged in locally
  const activeUserId =
    userId ||
    (typeof window !== 'undefined'
      ? localStorage.getItem('aura_user_id') ||
        localStorage.getItem('user_id') ||
        '02b7cfb6-f0b2-4d6e-a87b-0b85d4af5fb6'
      : '02b7cfb6-f0b2-4d6e-a87b-0b85d4af5fb6');

  return (
    <header className="w-full h-14 bg-slate-900 border-b border-slate-800 px-6 flex items-center justify-between">
      {/* App Logo / Name */}
      <div className="flex items-center gap-2">
        <span className="text-lg font-bold text-slate-100">AURA</span>
        <span className="text-xs px-2 py-0.5 rounded bg-indigo-900/60 text-indigo-300 font-mono border border-indigo-700/50">
          Workspace
        </span>
      </div>

      {/* Right Controls */}
      <div className="flex items-center gap-3">
        {/* Gateway Online Status */}
        <span className="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium bg-emerald-950 text-emerald-400 border border-emerald-800">
          <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse"></span>
          Gateway: Online
        </span>

        {/* Integration Buttons */}
        <ConnectGmailButton userId={activeUserId} />
        <GithubConnectButton userId={activeUserId} />

        <span className="text-xs text-slate-400 px-2 py-1 rounded bg-slate-800">
          Authenticated
        </span>
      </div>
    </header>
  );
}