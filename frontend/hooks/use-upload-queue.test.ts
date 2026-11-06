// @vitest-environment jsdom
// req: R-01
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { toast } from 'sonner';
import { useUploadQueue } from './use-upload-queue';
import { workspaceApi } from '@/lib/api';

vi.mock('sonner', () => ({ toast: { error: vi.fn(), message: vi.fn(), info: vi.fn() } }));
vi.mock('@/lib/api', () => ({ workspaceApi: { uploadFile: vi.fn() } }));

const file = () => new File(['x'], 'a.pdf', { type: 'application/pdf' });
afterEach(() => vi.clearAllMocks());

describe('upload queue', () => {
  it('upload with picked type sends doc_type to /v1/files', async () => {
    vi.mocked(workspaceApi.uploadFile).mockResolvedValue({} as never);
    const { result } = renderHook(() => useUploadQueue(async () => {}));
    act(() => result.current.enqueueUploads([file()], '', 'passport'));
    await waitFor(() => expect(workspaceApi.uploadFile).toHaveBeenCalled());
    expect(vi.mocked(workspaceApi.uploadFile).mock.calls[0][2]).toMatchObject({ docType: 'passport' });
  });

  it('something else sends no doc_type', async () => {
    vi.mocked(workspaceApi.uploadFile).mockResolvedValue({} as never);
    const { result } = renderHook(() => useUploadQueue(async () => {}));
    act(() => result.current.enqueueUploads([file()], ''));
    await waitFor(() => expect(workspaceApi.uploadFile).toHaveBeenCalled());
    expect(vi.mocked(workspaceApi.uploadFile).mock.calls[0][2]?.docType).toBeUndefined();
  });

  it('shows the server note when the file was saved but not registered', async () => {
    vi.mocked(workspaceApi.uploadFile).mockResolvedValue(
      { os_document: { refused: 'unknown_type', note: 'Saved. PAI cannot read this kind of document yet.' } } as never);
    const { result } = renderHook(() => useUploadQueue(async () => {}));
    act(() => result.current.enqueueUploads([file()], '', 'passport'));
    await waitFor(() => expect(toast.message).toHaveBeenCalledWith('Saved. PAI cannot read this kind of document yet.'));
  });

  it('a plain upload shows no note', async () => {
    vi.mocked(workspaceApi.uploadFile).mockResolvedValue({ id: 'f' } as never);
    const { result } = renderHook(() => useUploadQueue(async () => {}));
    act(() => result.current.enqueueUploads([file()], ''));
    await waitFor(() => expect(workspaceApi.uploadFile).toHaveBeenCalled());
    await waitFor(() => expect(result.current.uploads).toHaveLength(0));
    expect(toast.message).not.toHaveBeenCalled();
  });
});
