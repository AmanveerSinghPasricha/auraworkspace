"use client";

import React, { useState, useEffect } from "react";

interface ConnectGmailButtonProps {
  userId: string;
  apiBaseUrl?: string;
}

export const ConnectGmailButton: React.FC<ConnectGmailButtonProps> = ({
  userId,
  apiBaseUrl = "http://localhost:8000",
}) => {
  const [loading, setLoading] = useState<boolean>(false);
  const [isConnected, setIsConnected] = useState<boolean>(false);

  // Handle post-OAuth return callback from query params
  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const connectionId = urlParams.get("connection_id");

    if (connectionId && userId) {
      handleSaveCallback(connectionId);
    }
  }, [userId]);

  const handleSaveCallback = async (connectionId: str) => {
    try {
      setLoading(true);
      const res = await fetch(`${apiBaseUrl}/api/v1/integrations/gmail/callback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: userId,
          connection_id: connectionId,
        }),
      });

      if (res.ok) {
        setIsConnected(true);
        // Clean URL query parameters
        window.history.replaceState({}, document.title, window.location.pathname);
      }
    } catch (err) {
      console.error("Failed to save Smithery connection ID:", err);
    } finally {
      setLoading(false);
    }
  };

  const handleConnect = async () => {
    try {
      setLoading(true);
      const res = await fetch(
        `${apiBaseUrl}/api/v1/integrations/gmail/connect-url?user_id=${userId}`
      );
      
      if (!res.ok) throw new Error("Failed to fetch connection URL");
      
      const data = await res.json();
      // Redirect user to Smithery Hosted Dynamic OAuth
      window.location.href = data.connect_url;
    } catch (err) {
      console.error("Connection error:", err);
      setLoading(false);
    }
  };

  return (
    <button
      onClick={handleConnect}
      disabled={loading || isConnected}
      className={`px-4 py-2 rounded-lg font-medium transition-colors flex items-center gap-2 ${
        isConnected
          ? "bg-green-600 text-white cursor-default"
          : "bg-blue-600 hover:bg-blue-700 text-white disabled:bg-gray-400"
      }`}
    >
      {loading ? (
        <span>Connecting...</span>
      ) : isConnected ? (
        <span>✓ Gmail Connected</span>
      ) : (
        <span>Connect Gmail</span>
      )}
    </button>
  );
};

export default ConnectGmailButton;