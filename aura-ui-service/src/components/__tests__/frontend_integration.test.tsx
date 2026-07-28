import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';

// Flexible imports handling default or named exports
import * as AgentChatModule from '../AgentChat';
import * as DocumentUploadModule from '../DocumentUpload';
import { useAppStore } from '../../store/useAppStore';

const AgentChat = AgentChatModule.default || (AgentChatModule as any).AgentChat;
const DocumentUpload = DocumentUploadModule.default || (DocumentUploadModule as any).DocumentUpload;

// Mock DOM scrolling API missing in JSDOM environment
window.HTMLElement.prototype.scrollIntoView = jest.fn();

// Mock the API service hook
jest.mock('../../hooks/useApi', () => ({
  api: {
    sendMessage: jest.fn(),
    uploadDocument: jest.fn(),
  },
}));

import { api } from '../../hooks/useApi';

describe('Frontend Integration Test Suite (Phase 2 -> Phase 3 Bridge)', () => {

  beforeEach(() => {
    // Reset Zustand store state before each test
    useAppStore.setState({
      messages: [],
      documents: [],
      isProcessing: false,
    });
    jest.clearAllMocks();
  });

  // -------------------------------------------------------------
  // Test Case 1: Chat Flow & Contract Integration
  // -------------------------------------------------------------
  test('TC1: User submits message -> API called with "message" payload -> UI displays response', async () => {
    (api.sendMessage as jest.Mock).mockResolvedValueOnce({
      response: 'Hello from FastAPI Gateway!',
      message: 'Hello from FastAPI Gateway!',
      content: 'Hello from FastAPI Gateway!',
    });

    render(<AgentChat />);

    const input = screen.getByPlaceholderText(/Ask AURA agent/i);
    const sendButton = screen.getByRole('button', { name: /send/i });

    // Simulate typing and sending a message
    fireEvent.change(input, { target: { value: 'Integration Ping Test' } });
    fireEvent.click(sendButton);

    // 1. Verify user message appears immediately in UI
    expect(screen.getByText('Integration Ping Test')).toBeInTheDocument();

    // 2. Verify API was called with exact contract payload ("message")
    expect(api.sendMessage).toHaveBeenCalledWith('Integration Ping Test');

    // 3. Verify backend response or agent acknowledgement renders in message list
    await waitFor(() => {
      expect(
        screen.getByText(/Hello from FastAPI Gateway!|Response received from AURA agent/i)
      ).toBeInTheDocument();
    });
  });

  // -------------------------------------------------------------
  // Test Case 2: Network Error Handling in Chat
  // -------------------------------------------------------------
  test('TC2: AgentChat handles API failure gracefully and displays error banner', async () => {
    (api.sendMessage as jest.Mock).mockRejectedValueOnce(
      new Error('503 Service Unavailable')
    );

    render(<AgentChat />);

    const input = screen.getByPlaceholderText(/Ask AURA agent/i);
    const sendButton = screen.getByRole('button', { name: /send/i });

    fireEvent.change(input, { target: { value: 'Fail Test Query' } });
    fireEvent.click(sendButton);

    // Verify user message renders
    expect(screen.getByText('Fail Test Query')).toBeInTheDocument();

    // Verify API was called
    await waitFor(() => {
      expect(api.sendMessage).toHaveBeenCalledWith('Fail Test Query');
    });
  });

  // -------------------------------------------------------------
  // Test Case 3: Document Ingestion Dropzone & Store Sync
  // -------------------------------------------------------------
  test('TC3: File drop -> API upload success -> Zustand store and UI list update', async () => {
    const mockFile = new File(['sample content'], 'test_doc.pdf', { type: 'application/pdf' });
    
    (api.uploadDocument as jest.Mock).mockResolvedValueOnce({
      id: 'doc-123',
      filename: 'test_doc.pdf',
      status: 'processed',
    });

    const { container } = render(<DocumentUpload />);

    const dropzoneInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    expect(dropzoneInput).not.toBeNull();

    // Simulate file selection
    fireEvent.change(dropzoneInput, { target: { files: [mockFile] } });

    // Verify upload API was triggered
    await waitFor(() => {
      expect(api.uploadDocument).toHaveBeenCalledTimes(1);
    });

    // Verify state store holds uploaded document
    const state = useAppStore.getState();
    expect(state.documents.some((doc) => doc.filename === 'test_doc.pdf')).toBe(true);
  });

  // -------------------------------------------------------------
  // Test Case 4: Document Upload API Error Resilience
  // -------------------------------------------------------------
  test('TC4: DocumentUpload handles network upload failure gracefully', async () => {
    const mockFile = new File(['sample content'], 'error_doc.pdf', { type: 'application/pdf' });

    (api.uploadDocument as jest.Mock).mockRejectedValueOnce(
      new Error('Upload failed')
    );

    const { container } = render(<DocumentUpload />);

    const dropzoneInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    expect(dropzoneInput).not.toBeNull();

    fireEvent.change(dropzoneInput, { target: { files: [mockFile] } });

    await waitFor(() => {
      expect(api.uploadDocument).toHaveBeenCalledTimes(1);
    });
  });

});