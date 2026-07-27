import { create } from 'zustand';
import { Message, DocumentStatus, SystemHealth } from '../types';

interface AppState {
  health: SystemHealth;
  messages: Message[];
  documents: DocumentStatus[];
  setHealth: (health: SystemHealth) => void;
  addMessage: (message: Message) => void;
  addDocument: (doc: DocumentStatus) => void;
  updateDocumentStatus: (id: string, updates: Partial<DocumentStatus>) => void;
}

export const useAppStore = create<AppState>((set) => ({
  health: { status: 'connecting', gatewayUrl: 'http://localhost:8000' },
  messages: [],
  documents: [],
  
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
}));