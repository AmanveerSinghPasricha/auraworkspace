import { Message, DocumentStatus, SystemHealth } from '../types';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

export async function apiRequest<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;

  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...options.headers,
  };

  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `HTTP Error ${response.status}`);
  }

  return response.json();
}

export const api = {
  checkHealth: () => apiRequest<SystemHealth>('/health'),

  // FIXED: Changed payload key from 'prompt' to 'message' to match FastAPI schema
  sendMessage: (message: string) =>
    apiRequest<Message>('/api/v1/chat', {
      method: 'POST',
      body: JSON.stringify({ message }),
    }),

  // FIXED: Added auth bearer token and detail error parsing for uploads
  uploadDocument: async (formData: FormData): Promise<DocumentStatus> => {
    const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;

    const response = await fetch(`${API_BASE_URL}/api/v1/documents/upload`, {
      method: 'POST',
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        // Note: Do NOT set 'Content-Type' manually here so the browser sets multipart boundaries automatically
      },
      body: formData,
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || `Upload failed with status ${response.status}`);
    }

    return response.json();
  },
};