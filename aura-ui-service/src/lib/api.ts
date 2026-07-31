const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000/api/v1";

export interface SignUpPayload {
  email: string;
  password: string;
  full_name: string;
  role_or_title: string;
  primary_goal: string;
  preferred_tone: string;
  domain_expertise: string[];
  additional_context?: string;
}

export interface LoginPayload {
  email: string;
  password: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user_id: string;
  full_name: string;
}

export interface UserMemoryProfile {
  user_id: string;
  full_name: string;
  role_or_title: string;
  primary_goal: string;
  preferred_tone: string;
  domain_expertise: string[];
  additional_context?: string;
  profile_summary: string;
}

export async function signupUser(payload: SignUpPayload): Promise<AuthResponse> {
  const response = await fetch(`${API_BASE_URL}/auth/signup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const errorData = await response.json();
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
    const errorData = await response.json();
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