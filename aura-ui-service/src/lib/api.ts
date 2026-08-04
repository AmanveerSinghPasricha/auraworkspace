// Dynamically reads from process.env or falls back cleanly to http://127.0.0.1:8000
const BASE_HOST =
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://127.0.0.1:8000";

// Ensures base URL points cleanly to the API v1 namespace without trailing slash issues
const API_BASE_URL = BASE_HOST.endsWith("/api/v1")
  ? BASE_HOST
  : `${BASE_HOST.replace(/\/$/, "")}/api/v1`;

export interface SignUpPayload {
  email: string;
  password: string;
  full_name: string;
  role_or_title?: string;
  primary_goal?: string;
  preferred_tone?: string;
  domain_expertise?: string[];
  additional_context?: string;
}

export interface LoginPayload {
  email: string;
  password: string;
}

export interface AuthResponse {
  access_token: string;
  token_type?: string;
  user_id: string;
  full_name: string;
}

export interface UserMemoryProfile {
  user_id: string;
  full_name: string;
  role_or_title?: string;
  primary_goal?: string;
  preferred_tone?: string;
  domain_expertise?: string[];
  additional_context?: string;
  profile_summary: string;
}

export interface ChatPayload {
  message: string;
  user_id?: string;
  thread_id?: string;
}

export interface ResumePayload {
  thread_id: string;
  approved: boolean;
}

export interface ResumeResponse {
  thread_id: string;
  response: string;
  status: string;
}

export interface ConnectSmitheryPayload {
  user_id: string;
  smithery_connection_id: string;
}

/**
 * Checks gateway backend health status
 */
export async function checkHealth(): Promise<{ status: string }> {
  const response = await fetch(`${BASE_HOST.replace(/\/$/, "")}/health`);
  if (!response.ok) {
    throw new Error("Backend service is offline.");
  }
  return response.json();
}

/**
 * Sends chat prompt to AURA Gateway /chat endpoint
 */
export async function sendMessage(
  message: string,
  userId?: string,
  threadId: string = "thread_demo_001"
): Promise<any> {
  const token = typeof window !== "undefined" ? localStorage.getItem("aura_token") : null;
  const storedUserId = typeof window !== "undefined" ? localStorage.getItem("aura_user_id") : null;

  const resolvedUserId = userId || storedUserId || "02b7cfb6-f0b2-4d6e-a87b-0b85d4af5fb6";

  const response = await fetch(`${API_BASE_URL}/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({
      message,
      user_id: resolvedUserId,
      thread_id: threadId,
    }),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || "Failed to communicate with gateway core.");
  }

  return response.json();
}

export async function signupUser(payload: SignUpPayload): Promise<AuthResponse> {
  const response = await fetch(`${API_BASE_URL}/auth/signup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || "Signup failed.");
  }

  return response.json();
}

export async function loginUser(payload: LoginPayload): Promise<AuthResponse> {
  const response = await fetch(`${API_BASE_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || "Invalid email or password.");
  }

  return response.json();
}

export async function getUserMemoryProfile(userId: string): Promise<UserMemoryProfile> {
  const response = await fetch(`${API_BASE_URL}/auth/memory/profile/${userId}`);

  if (!response.ok) {
    throw new Error("Failed to load user memory profile.");
  }

  return response.json();
}

/**
 * Sends a human approval or rejection decision to resume an interrupted LangGraph workflow.
 */
export async function resumeChat(payload: ResumePayload): Promise<ResumeResponse> {
  const token = typeof window !== "undefined" ? localStorage.getItem("aura_token") : null;

  const response = await fetch(`${API_BASE_URL}/chat/resume`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || "Failed to submit execution decision to backend.");
  }

  return response.json();
}

/**
 * Links a user's authenticated Smithery OAuth Connection ID to their PostgreSQL profile.
 */
export async function connectSmitheryAccount(payload: ConnectSmitheryPayload): Promise<any> {
  const token = typeof window !== "undefined" ? localStorage.getItem("aura_token") : null;

  const response = await fetch(`${API_BASE_URL}/auth/connect-smithery`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || "Failed to link Smithery connection ID.");
  }

  return response.json();
}

// Consolidated Object Export for component consumption
export const api = {
  checkHealth,
  sendMessage,
  signupUser,
  loginUser,
  getUserMemoryProfile,
  resumeChat,
  connectSmitheryAccount,
};