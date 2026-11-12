// req: R-72
import { describe, expect, it, vi } from 'vitest';
import { evidenceDelivery, openEvidence, safeFilename } from './os-review';

const env = () => ({
  createObjectURL: vi.fn((b: Blob) => `blob:${b.type}`), revokeObjectURL: vi.fn(),
  open: vi.fn(), download: vi.fn(),
});

describe('evidence is never opened as a page in the app origin (C1)', () => {
  it('shows only PDF and images', () => {
    for (const t of ['application/pdf', 'image/png', 'image/jpeg', 'image/webp', 'IMAGE/PNG; charset=x']) {
      expect(evidenceDelivery(t)).toBe('view');
    }
    for (const t of ['text/html', 'image/svg+xml', 'text/plain', 'application/xhtml+xml', 'text/xml', '', 'application/javascript']) {
      expect(evidenceDelivery(t)).toBe('download');
    }
  });

  it('opens a PDF in a tab with its own type', () => {
    const e = env();
    openEvidence(new Blob(['x'], { type: 'application/pdf' }), 'a.pdf', e);
    expect(e.open).toHaveBeenCalledWith('blob:application/pdf');
    expect(e.download).not.toHaveBeenCalled();
  });

  it.each(['text/html', 'image/svg+xml', 'text/plain', ''])('forces a download as octet-stream for %s', (type) => {
    const e = env();
    openEvidence(new Blob(['<script>1</script>'], { type }), 'page.html', e);
    expect(e.open).not.toHaveBeenCalled();
    expect(e.createObjectURL).toHaveBeenCalledTimes(1);
    expect((e.createObjectURL.mock.calls[0][0] as Blob).type).toBe('application/octet-stream');
    expect(e.download).toHaveBeenCalledWith('blob:application/octet-stream', 'page.html');
    expect(e.revokeObjectURL).toHaveBeenCalled();
  });

  it('cleans the file name', () => {
    expect(safeFilename('a"b<c>.html')).toBe('a_b_c_.html');
    expect(safeFilename('../x/y.txt')).not.toMatch(/[\\/]/);
    expect(safeFilename('"<>')).toBe('_');
    expect(safeFilename('')).toBe('evidence');
  });
});
