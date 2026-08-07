"use client";

import React, { useState, useEffect, useCallback } from "react";

interface ConnectGmailButtonProps {
  userId: string;
  apiBaseUrl?: string;
}

export const ConnectGmailButton: React.FC<ConnectGmailButtonProps> = ({
  userId,
  apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000",
}) => {
  const [loading, setLoading] = useState<boolean>(false);
  const [isConnected, setIsConnected] = useState<boolean>(false);

  const handleSaveCallback = useCallback(
    async (code: string) => {
      try {
        setLoading(true);
        const redirectUri = `${window.location.origin}/auth/gmail/callback`;

        const res = await fetch(`${apiBaseUrl}/api/v1/auth/connect-gmail`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            user_id: userId,
            code: code,
            redirect_uri: redirectUri,
          }),
        });

        if (res.ok) {
          setIsConnected(true);
          window.history.replaceState({}, document.title, window.location.pathname);
        } else {
          console.error("Failed to persist Gmail connection.");
        }
      } catch (err) {
        console.error("Failed to connect Gmail account:", err);
      } finally {
        setLoading(false);
      }
    },
    [apiBaseUrl, userId]
  );

  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const code = urlParams.get("code");

    if (code && userId) {
      handleSaveCallback(code);
    }
  }, [userId, handleSaveCallback]);

  const handleConnect = () => {
    try {
      setLoading(true);
      const clientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;

      if (!clientId) {
        alert("Google Client ID is missing in frontend configuration.");
        setLoading(false);
        return;
      }

      const redirectUri = `${window.location.origin}/auth/gmail/callback`;
      const scope = "https://www.googleapis.com/auth/gmail.send";

      const googleAuthUrl =
        `https://accounts.google.com/o/oauth2/v2/auth?` +
        `client_id=${encodeURIComponent(clientId)}` +
        `&redirect_uri=${encodeURIComponent(redirectUri)}` +
        `&response_type=code` +
        `&scope=${encodeURIComponent(scope)}` +
        `&access_type=offline` +
        `&prompt=consent`;

      window.location.href = googleAuthUrl;
    } catch (err) {
      console.error("OAuth flow start error:", err);
      setLoading(false);
    }
  };

  return (
    <button
      onClick={handleConnect}
      disabled={loading || isConnected}
      className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-all flex items-center gap-1.5 shadow-sm ${
        isConnected
          ? "bg-emerald-950 text-emerald-400 border border-emerald-800 cursor-default"
          : "bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50"
      }`}
    >
      {loading ? (
        <span>Connecting...</span>
      ) : isConnected ? (
        <span>✓ Gmail Connected</span>
      ) : (
        <span>✉️ Connect Gmail</span>
      )}
    </button>
  );
};

export default ConnectGmailButton;