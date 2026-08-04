'use client';

import React from 'react';
import { GithubConnectButton } from '@/components/GithubConnectButton';

interface HeaderProps {
  userId?: string;
  userEmail?: string;
}

export function Header({ userId, userEmail }: HeaderProps) {
  // Retrieve logged-in user ID from props, localStorage, or state
  const activeUserId = userId || (typeof window !== 'undefined' ? localStorage.getItem('aura_user_id') : null);

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
      <div className="flex items-center gap-4">
        {/* GitHub Integration Button */}
        {activeUserId ? (
          <GithubConnectButton userId={activeUserId} />
        ) : (
          <span className="text-xs text-slate-500">Sign in to connect integrations</span>
        )}

        {/* User Info */}
        {userEmail && (
          <div className="text-xs text-slate-400 border-l border-slate-800 pl-4">
            {userEmail}
          </div>
        )}
      </div>
    </header>
  );
}