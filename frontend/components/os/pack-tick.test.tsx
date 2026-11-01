// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { PackView } from './pack';
import type { OsPack } from '@/lib/os-packs';

afterEach(cleanup);

// Fictional values only.
function pack(ticked: boolean): OsPack {
  return {
    programme_ref: 'p1', name: 'MSc Example', university: 'Uni Sample', status: 'incomplete', version: 2,
    approved: false, manifest_sha256: 'a'.repeat(64), route_value: 'uni_assist', instructions: [], fees: [],
    checklist: [{ key: 'degree', label: 'Degree', kind: 'document', state: 'needs_action', ticked, reasons: [],
                  source: 'default', document_id: 2, tickable: true }],
    after_approval: [], data_sheet: [], files: [],
  };
}

const noop = () => {};

function show(p: OsPack, onTick: (key: string, ticked: boolean) => Promise<boolean>) {
  return render(<PackView pack={p} busy={false} onTick={onTick} onAdd={noop} onApprove={noop} onDownload={noop}
                          onRebuild={noop} onDetails={noop} />);
}

describe('checklist ticks', () => {
  it('show at once and stay while the server still sends the old state', async () => {
    const onTick = vi.fn(async () => true);
    const view = show(pack(false), onTick);
    const box = screen.getByRole('checkbox', { name: 'Degree' }) as HTMLInputElement;
    await act(async () => { fireEvent.click(box); });
    expect(onTick).toHaveBeenCalledWith('degree', true);
    expect(box.checked).toBe(true);
    view.rerender(<PackView pack={pack(false)} busy={false} onTick={onTick} onAdd={noop} onApprove={noop}
                            onDownload={noop} onRebuild={noop} onDetails={noop} />);  // a rebuild, still old
    expect((screen.getByRole('checkbox', { name: 'Degree' }) as HTMLInputElement).checked).toBe(true);
  });

  it('go back when saving was refused', async () => {
    const view = show(pack(false), async () => false);
    await act(async () => { fireEvent.click(screen.getByRole('checkbox', { name: 'Degree' })); });
    expect((screen.getByRole('checkbox', { name: 'Degree' }) as HTMLInputElement).checked).toBe(false);
    view.unmount();
  });
});
