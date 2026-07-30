"use client";

import { useState } from "react";
import Link from "next/link";
import { loginUser } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

export default function LoginPage() {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);

    try {
      const authData = await loginUser({ email, password });
      login(authData);
    } catch (err: any) {
      setError(err?.message || "Invalid credentials. Please try again.");
      setIsSubmitting(false);
    }
  };

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-slate-950 p-4 text-slate-100">
      {/* Background Ambient Glow */}
      <div className="pointer-events-none absolute left-1/2 top-1/4 h-[500px] w-[500px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-gradient-to-tr from-blue-600/20 to-teal-500/20 blur-3xl" />

      {/* Main Login Card */}
      <div className="relative z-10 w-full max-w-sm rounded-2xl border border-slate-800 bg-slate-900/90 p-8 shadow-2xl backdrop-blur-xl">
        <div className="mb-6 text-center">
          <div className="mb-3 inline-flex h-12 w-12 items-center justify-center rounded-xl border border-blue-500/20 bg-blue-600/10 text-xl font-bold text-blue-400">
            🔐
          </div>
          <h1 className="bg-gradient-to-r from-blue-400 via-teal-300 to-emerald-400 bg-clip-text text-2xl font-bold tracking-tight text-transparent">
            Aura Workspace
          </h1>
          <p className="mt-1.5 text-xs font-medium text-slate-400">
            Sign in to your account
          </p>
        </div>

        {/* Error Alert Box */}
        {error && (
          <div className="mb-5 flex items-center gap-2 rounded-xl border border-red-800/80 bg-red-950/60 p-3 text-xs text-red-300">
            <span>⚠️</span>
            <span>{error}</span>
          </div>
        )}

        {/* Form Inputs */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="mb-1.5 block text-[11px] font-bold uppercase tracking-wider text-slate-400">
              Email
            </label>
            <input
              type="email"
              required
              placeholder="jane@company.com"
              className="w-full rounded-xl border border-slate-700/80 bg-slate-800/80 px-4 py-2.5 text-sm text-white placeholder-slate-500 transition-all focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>

          <div>
            <label className="mb-1.5 block text-[11px] font-bold uppercase tracking-wider text-slate-400">
              Password
            </label>
            <input
              type="password"
              required
              placeholder="••••••••"
              className="w-full rounded-xl border border-slate-700/80 bg-slate-800/80 px-4 py-2.5 text-sm text-white placeholder-slate-500 transition-all focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>

          <button
            type="submit"
            disabled={isSubmitting}
            className="mt-6 w-full rounded-xl bg-gradient-to-r from-blue-600 to-blue-500 py-3 text-xs font-semibold text-white shadow-lg shadow-blue-600/25 transition-all hover:from-blue-500 hover:to-blue-400 disabled:opacity-50"
          >
            {isSubmitting ? "Signing in..." : "Sign In"}
          </button>
        </form>

        <div className="mt-6 text-center text-xs text-slate-500">
          Don't have an account?{" "}
          <Link
            href="/signup"
            className="font-medium text-blue-400 transition-colors hover:text-blue-300 hover:underline"
          >
            Create Account
          </Link>
        </div>
      </div>
    </div>
  );
}