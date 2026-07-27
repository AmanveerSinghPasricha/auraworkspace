export interface Message {
  id: string;
  sender: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: string;
  toolCalls?: {
    toolName: string;
    input: Record<string, unknown>;
    output?: string;
  }[];
}

export interface DocumentStatus {
  id: string;
  filename: string;
  status: 'uploading' | 'processing' | 'completed' | 'failed';
  progress: number;
  error?: string;
}

export interface SystemHealth {
  status: 'online' | 'offline' | 'connecting';
  gatewayUrl: string;
  timestamp?: string;
}