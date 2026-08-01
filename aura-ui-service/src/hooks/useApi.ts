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

  sendMessage: (message: string) =>
    apiRequest<Message>('/api/v1/chat', {
      method: 'POST',
      body: JSON.stringify({ message }),
    }),

  uploadDocument: async (formData: FormData): Promise<DocumentStatus & { job_id?: string }> => {
    const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;

    const response = await fetch(`${API_BASE_URL}/api/v1/documents/upload`, {
      method: 'POST',
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: formData,
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || `Upload failed with status ${response.status}`);
    }

    return response.json();
  },

  getIngestionStatus: (jobId: string) =>
    apiRequest<{
      status: 'queued' | 'processing' | 'completed' | 'failed';
      progress?: number;
      filename?: string;
      error?: string;
    }>(`/api/v1/documents/status/${jobId}`),
};