import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { DocumentUpload } from '../DocumentUpload';
import { api } from '../../hooks/useApi';
import { useAppStore } from '../../store/useAppStore';

jest.mock('../../hooks/useApi', () => ({
  api: {
    uploadDocument: jest.fn(),
  },
}));

describe('DocumentUpload Component', () => {
  beforeEach(() => {
    useAppStore.setState({ documents: [] });
    jest.clearAllMocks();
  });

  test('renders dropzone correctly', () => {
    render(<DocumentUpload />);
    expect(screen.getByText(/Click or drop documents here/i)).toBeInTheDocument();
  });

  test('handles file upload flow successfully', async () => {
    const mockDocStatus = {
      id: 'doc-123',
      filename: 'sample.pdf',
      status: 'completed' as const,
      progress: 100,
    };

    (api.uploadDocument as jest.Mock).mockResolvedValueOnce(mockDocStatus);

    render(<DocumentUpload />);

    const file = new File(['dummy content'], 'sample.pdf', { type: 'application/pdf' });
    const dropzone = screen.getByText(/Click or drop documents here/i);

    // Simulate drag and drop
    fireEvent.drop(dropzone, {
      dataTransfer: {
        files: [file],
      },
    });

    // Verify filename appears in the list
    expect(screen.getByText('sample.pdf')).toBeInTheDocument();

    await waitFor(() => {
      expect(api.uploadDocument).toHaveBeenCalled();
      expect(screen.getByText('completed')).toBeInTheDocument();
    });
  });
});