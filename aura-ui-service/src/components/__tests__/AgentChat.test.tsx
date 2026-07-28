import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { AgentChat } from '../AgentChat';
import { api } from '../../hooks/useApi';
import { useAppStore } from '../../store/useAppStore';

// Mock API client
jest.mock('../../hooks/useApi', () => ({
  api: {
    sendMessage: jest.fn(),
  },
}));

describe('AgentChat Component', () => {
  beforeEach(() => {
    // Reset Zustand store state before each test
    useAppStore.setState({ messages: [] });
    jest.clearAllMocks();
    
    // Mock scrollIntoView for DOM element
    Element.prototype.scrollIntoView = jest.fn();
  });

  test('renders empty chat placeholder initially', () => {
    render(<AgentChat />);
    expect(screen.getByText(/Start a conversation with AURA AI/i)).toBeInTheDocument();
  });

  test('sends user message and displays assistant response', async () => {
    const mockResponse = {
      id: '2',
      sender: 'assistant' as const,
      content: 'Hello! I am AURA.',
      timestamp: '12:00 PM',
    };

    (api.sendMessage as jest.Mock).mockResolvedValueOnce(mockResponse);

    render(<AgentChat />);

    const input = screen.getByPlaceholderText(/Ask AURA agent or request document analysis.../i);
    const sendButton = screen.getByRole('button', { name: /Send/i });

    // Simulate typing and submitting prompt
    fireEvent.change(input, { target: { value: 'Hi AURA' } });
    fireEvent.click(sendButton);

    // Verify user message appears immediately
    expect(screen.getByText('Hi AURA')).toBeInTheDocument();

    // Verify API is called with user prompt
    expect(api.sendMessage).toHaveBeenCalledWith('Hi AURA');

    // Wait for assistant response to render
    await waitFor(() => {
      expect(screen.getByText('Hello! I am AURA.')).toBeInTheDocument();
    });
  });

  test('displays fallback error message when API fails', async () => {
    (api.sendMessage as jest.Mock).mockRejectedValueOnce(new Error('Network error'));

    render(<AgentChat />);

    const input = screen.getByPlaceholderText(/Ask AURA agent or request document analysis.../i);
    const sendButton = screen.getByRole('button', { name: /Send/i });

    fireEvent.change(input, { target: { value: 'Test Error' } });
    fireEvent.click(sendButton);

    await waitFor(() => {
      expect(
        screen.getByText(/Failed to get response from gateway/i)
      ).toBeInTheDocument();
    });
  });
});