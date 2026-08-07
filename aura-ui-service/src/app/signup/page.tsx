"use client";

import { useState } from "react";
import Link from "next/link";
import { signupUser, SignUpPayload } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

export default function SignUpPage() {
  const { login } = useAuth();
  const [step, setStep] = useState<1 | 2>(1);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const [formData, setFormData] = useState<SignUpPayload>({
    email: "",
    password: "",
    full_name: "",
    role_or_title: "",
    primary_goal: "",
    preferred_tone: "Direct & Concise",
    domain_expertise: [],
    additional_context: "",
  });

  const [tagInput, setTagInput] = useState("");

  const handleAddTag = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      const trimmedTag = tagInput.trim();
      if (trimmedTag && !formData.domain_expertise.includes(trimmedTag)) {
        setFormData((prev) => ({
          ...prev,
          domain_expertise: [...prev.domain_expertise, trimmedTag],
        }));
        setTagInput("");
      }
    }
  };

  const handleRemoveTag = (tagToRemove: string) => {
    setFormData((prev) => ({
      ...prev,
      domain_expertise: prev.domain_expertise.filter((tag) => tag !== tagToRemove),
    }));
  };

  const handleNext = (e: React.FormEvent) => {
    e.preventDefault();
    if (!formData.full_name.trim() || !formData.email.trim() || !formData.password.trim()) {
      setError("Please fill in all required account fields.");
      return;
    }
    if (formData.password.length < 8) {
      setError("Password must be at least 8 characters long.");
      return;
    }
    setError(null);
    setStep(2);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);

    try {
      // Sends payload to FastAPI at http://localhost:8000/api/v1/auth/signup
      const authData = await signupUser(formData);
      
      // Log user in with returned JWT token
      if (authData && authData.access_token) {
        login(authData);
      } else {
        throw new Error("No access token returned from server.");
      }
    } catch (err: any) {
      console.error("Signup error:", err);
      setError(err?.message || "An error occurred during registration. Make sure backend is running on port 8000.");
      setIsSubmitting(false);
    }
  };

  return (
    <div style={{ minHeight: "100vh", backgroundColor: "#020617", color: "#f8fafc", display: "flex", alignItems: "center", justifyContent: "center", padding: "1rem", position: "relative", overflow: "hidden" }}>
      
      {/* Centered Form Card */}
      <div 
        className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900/90 p-8 shadow-2xl backdrop-blur-xl"
        style={{ width: "100%", maxWidth: "28rem", backgroundColor: "#0f172a", borderRadius: "1rem", border: "1px solid #1e293b", padding: "2rem", boxSizing: "border-box" }}
      >
        {/* Header */}
        <div style={{ textAlign: "center", marginBottom: "1.5rem" }}>
          <div style={{ display: "inline-flex", width: "3rem", height: "3rem", alignItems: "center", justifyContent: "center", borderRadius: "0.75rem", backgroundColor: "rgba(37,99,235,0.1)", border: "1px solid rgba(59,130,246,0.2)", fontSize: "1.25rem", color: "#60a5fa", marginBottom: "0.75rem" }}>
            ✨
          </div>
          <h1 style={{ fontSize: "1.5rem", fontWeight: "700", color: "#ffffff", margin: 0 }}>
            Aura Workspace
          </h1>
          <p style={{ fontSize: "0.75rem", color: "#94a3b8", marginTop: "0.375rem" }}>
            {step === 1 ? "Step 1 of 2: Create your account" : "Step 2 of 2: AI Long-Term Memory Setup"}
          </p>
        </div>

        {/* Step Indicator Bar */}
        <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1.5rem" }}>
          <div style={{ height: "0.25rem", flex: 1, borderRadius: "9999px", backgroundColor: step >= 1 ? "#3b82f6" : "#1e293b" }} />
          <div style={{ height: "0.25rem", flex: 1, borderRadius: "9999px", backgroundColor: step >= 2 ? "#3b82f6" : "#1e293b" }} />
        </div>

        {/* Error Alert */}
        {error && (
          <div style={{ marginBottom: "1.25rem", padding: "0.75rem", backgroundColor: "rgba(69,10,10,0.6)", border: "1px solid rgba(153,27,27,0.8)", borderRadius: "0.75rem", color: "#fca5a5", fontSize: "0.75rem", display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <span>⚠️</span>
            <span>{error}</span>
          </div>
        )}

        {/* STEP 1: Basic Credentials */}
        {step === 1 ? (
          <form onSubmit={handleNext} style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
            <div>
              <label style={{ display: "block", fontSize: "0.7rem", fontWeight: "700", textTransform: "uppercase", color: "#94a3b8", marginBottom: "0.375rem", letterSpacing: "0.05em" }}>
                Full Name
              </label>
              <input
                type="text"
                required
                placeholder="Jane Doe"
                style={{ width: "100%", backgroundColor: "#1e293b", border: "1px solid #334155", borderRadius: "0.75rem", padding: "0.625rem 1rem", fontSize: "0.875rem", color: "#ffffff", outline: "none", boxSizing: "border-box" }}
                value={formData.full_name}
                onChange={(e) => setFormData({ ...formData, full_name: e.target.value })}
              />
            </div>

            <div>
              <label style={{ display: "block", fontSize: "0.7rem", fontWeight: "700", textTransform: "uppercase", color: "#94a3b8", marginBottom: "0.375rem", letterSpacing: "0.05em" }}>
                Work Email
              </label>
              <input
                type="email"
                required
                placeholder="jane@company.com"
                style={{ width: "100%", backgroundColor: "#1e293b", border: "1px solid #334155", borderRadius: "0.75rem", padding: "0.625rem 1rem", fontSize: "0.875rem", color: "#ffffff", outline: "none", boxSizing: "border-box" }}
                value={formData.email}
                onChange={(e) => setFormData({ ...formData, email: e.target.value })}
              />
            </div>

            <div>
              <label style={{ display: "block", fontSize: "0.7rem", fontWeight: "700", textTransform: "uppercase", color: "#94a3b8", marginBottom: "0.375rem", letterSpacing: "0.05em" }}>
                Password
              </label>
              <input
                type="password"
                required
                minLength={8}
                placeholder="••••••••"
                style={{ width: "100%", backgroundColor: "#1e293b", border: "1px solid #334155", borderRadius: "0.75rem", padding: "0.625rem 1rem", fontSize: "0.875rem", color: "#ffffff", outline: "none", boxSizing: "border-box" }}
                value={formData.password}
                onChange={(e) => setFormData({ ...formData, password: e.target.value })}
              />
            </div>

            <button
              type="submit"
              style={{ width: "100%", marginTop: "0.5rem", backgroundColor: "#2563eb", color: "#ffffff", fontSize: "0.875rem", fontWeight: "600", padding: "0.75rem", borderRadius: "0.75rem", border: "none", cursor: "pointer" }}
            >
              Next: Memory Profiling →
            </button>
          </form>
        ) : (
          /* STEP 2: Memory Profiling */
          <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
            <div>
              <label style={{ display: "block", fontSize: "0.7rem", fontWeight: "700", textTransform: "uppercase", color: "#94a3b8", marginBottom: "0.375rem" }}>
                Your Role / Title
              </label>
              <input
                type="text"
                placeholder="e.g. Lead Software Developer"
                style={{ width: "100%", backgroundColor: "#1e293b", border: "1px solid #334155", borderRadius: "0.75rem", padding: "0.625rem 1rem", fontSize: "0.875rem", color: "#ffffff", outline: "none", boxSizing: "border-box" }}
                value={formData.role_or_title}
                onChange={(e) => setFormData({ ...formData, role_or_title: e.target.value })}
              />
            </div>

            <div>
              <label style={{ display: "block", fontSize: "0.7rem", fontWeight: "700", textTransform: "uppercase", color: "#94a3b8", marginBottom: "0.375rem" }}>
                Primary Goal for Aura AI
              </label>
              <textarea
                rows={2}
                placeholder="e.g. Code reports and architectural design summaries."
                style={{ width: "100%", backgroundColor: "#1e293b", border: "1px solid #334155", borderRadius: "0.75rem", padding: "0.625rem 1rem", fontSize: "0.875rem", color: "#ffffff", outline: "none", resize: "none", boxSizing: "border-box" }}
                value={formData.primary_goal}
                onChange={(e) => setFormData({ ...formData, primary_goal: e.target.value })}
              />
            </div>

            <div>
              <label style={{ display: "block", fontSize: "0.7rem", fontWeight: "700", textTransform: "uppercase", color: "#94a3b8", marginBottom: "0.375rem" }}>
                Preferred AI Response Tone
              </label>
              <select
                style={{ width: "100%", backgroundColor: "#1e293b", border: "1px solid #334155", borderRadius: "0.75rem", padding: "0.625rem 1rem", fontSize: "0.875rem", color: "#ffffff", outline: "none", boxSizing: "border-box" }}
                value={formData.preferred_tone}
                onChange={(e) => setFormData({ ...formData, preferred_tone: e.target.value })}
              >
                <option value="Direct & Concise">Direct & Concise</option>
                <option value="Detailed & Technical">Detailed & Technical</option>
                <option value="Conversational & Friendly">Conversational & Friendly</option>
                <option value="Executive Summary Style">Executive Summary Style</option>
              </select>
            </div>

            <div>
              <label style={{ display: "block", fontSize: "0.7rem", fontWeight: "700", textTransform: "uppercase", color: "#94a3b8", marginBottom: "0.375rem" }}>
                Domain Expertise (Press Enter to add tags)
              </label>
              <input
                type="text"
                placeholder="Type tag and press Enter"
                style={{ width: "100%", backgroundColor: "#1e293b", border: "1px solid #334155", borderRadius: "0.75rem", padding: "0.625rem 1rem", fontSize: "0.875rem", color: "#ffffff", outline: "none", boxSizing: "border-box" }}
                value={tagInput}
                onChange={(e) => setTagInput(e.target.value)}
                onKeyDown={handleAddTag}
              />
              {formData.domain_expertise.length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: "0.375rem", marginTop: "0.5rem" }}>
                  {formData.domain_expertise.map((tag) => (
                    <span
                      key={tag}
                      style={{ display: "inline-flex", alignItems: "center", gap: "0.25rem", borderRadius: "9999px", border: "1px solid rgba(59,130,246,0.3)", backgroundColor: "rgba(59,130,246,0.1)", padding: "0.125rem 0.625rem", fontSize: "0.75rem", color: "#93c5fd" }}
                    >
                      {tag}
                      <button
                        type="button"
                        onClick={() => handleRemoveTag(tag)}
                        style={{ background: "none", border: "none", color: "#93c5fd", cursor: "pointer", fontWeight: "bold", marginLeft: "0.25rem" }}
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              )}
            </div>

            <div>
              <label style={{ display: "block", fontSize: "0.7rem", fontWeight: "700", textTransform: "uppercase", color: "#94a3b8", marginBottom: "0.375rem" }}>
                Additional Instructions / Preferences (Optional)
              </label>
              <input
                type="text"
                placeholder="e.g. Always keep response elaborate"
                style={{ width: "100%", backgroundColor: "#1e293b", border: "1px solid #334155", borderRadius: "0.75rem", padding: "0.625rem 1rem", fontSize: "0.875rem", color: "#ffffff", outline: "none", boxSizing: "border-box" }}
                value={formData.additional_context || ""}
                onChange={(e) => setFormData({ ...formData, additional_context: e.target.value })}
              />
            </div>

            <div style={{ display: "flex", gap: "0.75rem", paddingTop: "0.5rem" }}>
              <button
                type="button"
                onClick={() => {
                  setError(null);
                  setStep(1);
                }}
                style={{ width: "33.3%", backgroundColor: "#334155", color: "#cbd5e1", fontSize: "0.75rem", fontWeight: "600", padding: "0.75rem", borderRadius: "0.75rem", border: "none", cursor: "pointer" }}
              >
                ← Back
              </button>
              <button
                type="submit"
                disabled={isSubmitting}
                style={{ width: "66.6%", backgroundColor: "#2563eb", color: "#ffffff", fontSize: "0.75rem", fontWeight: "600", padding: "0.75rem", borderRadius: "0.75rem", border: "none", cursor: "pointer", opacity: isSubmitting ? 0.5 : 1 }}
              >
                {isSubmitting ? "Creating Account..." : "Complete Setup ✓"}
              </button>
            </div>
          </form>
        )}

        {/* Footer Link */}
        <div style={{ marginTop: "1.5rem", textAlign: "center", fontSize: "0.75rem", color: "#64748b" }}>
          Already have an account?{" "}
          <Link href="/login" style={{ color: "#60a5fa", fontWeight: "500", textDecoration: "none" }}>
            Sign In
          </Link>
        </div>
      </div>
    </div>
  );
}