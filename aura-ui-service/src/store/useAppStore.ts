import { create } from 'zustand';
import { Message, DocumentStatus, SystemHealth } from '../types';

export interface IngestedDocument {
  filename: string;
  file_path: string;
  file_hash: string;
  chapters_detected: number;
  document_ref: string;
}

interface AppState {
  health: SystemHealth;
  messages: Message[];
  documents: DocumentStatus[];
  activeDocument: IngestedDocument | null;
  
  setHealth: (health: SystemHealth) => void;
  addMessage: (message: Message) => void;
  addDocument: (doc: DocumentStatus) => void;
  updateDocumentStatus: (id: string, updates: Partial<DocumentStatus>) => void;
  
  // Active document context for RAG executions
  setActiveDocument: (doc: IngestedDocument | null) => void;
  clearActiveDocument: () => void;
}

export const useAppStore = create<AppState>((set) => ({
  health: { status: 'connecting', gatewayUrl: 'http://localhost:8000' },
  messages: [],
  documents: [],
  activeDocument: null,
  
  setHealth: (health) => set({ health }),
  
  addMessage: (message) =>
    set((state) => ({ messages: [...state.messages, message] })),
    
  addDocument: (doc) =>
    set((state) => ({ documents: [...state.documents, doc] })),
    
  updateDocumentStatus: (id, updates) =>
    set((state) => ({
      documents: state.documents.map((doc) =>
        doc.id === id ? { ...doc, ...updates } : doc
      ),
    })),

  setActiveDocument: (doc) => set({ activeDocument: doc }),
  
  clearActiveDocument: () => set({ activeDocument: null }),
}));