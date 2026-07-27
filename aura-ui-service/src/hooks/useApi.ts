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
  
  sendMessage: (prompt: string) =>
    apiRequest<Message>('/api/v1/chat', {
      method: 'POST',
      body: JSON.stringify({ prompt }),
    }),

  uploadDocument: (formData: FormData) =>
    fetch(`${API_BASE_URL}/api/v1/documents/upload`, {
      method: 'POST',
      body: formData,
    }).then((res) => {
      if (!res.ok) throw new Error('Document upload failed');
      return res.json() as Promise<DocumentStatus>;
    }),
};