// @vitest-environment jsdom
// req: R-16
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { DocumentConfirm } from "./document-confirm";
import { workspaceApi } from "@/lib/api";
import type { OsDocument } from "@/lib/os-documents";

vi.mock("@/lib/api", () => ({ workspaceApi: { getUploadOptions: vi.fn(), getOsVaultCheck: vi.fn() } }));

const NOTE = "PAI has a different value saved for this. Check which one is right.";
const TEXT = { type_label: "a", type_none: "b", registered: "c", consent_needed: "d", duplicate: "e", unknown_type: "f", not_readable: "g", not_now: "h" };
const doc: OsDocument = {
  id: 4, doc_type: "transcript", filename: "t.pdf", status: "read", detected_type: "transcript", pages: 1, error: null,
  created_at: "2026-10-21T08:00:00Z", read_at: null, confirmed_at: null, findings: [],
  fields: [
    { field: "cgpa", value_read: "3.1", check: "ok", reasons: [], value_confirmed: null },
    { field: "scale", value_read: "4", check: "ok", reasons: [], value_confirmed: null },
  ],
};
const ON = { one_upload: true as const, doc_types: [], text: TEXT };
const on = () => {};
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("confirm screen vault check", () => {
  it("shows the vault note once and a different marker on the differing field", async () => {
    on();
    vi.mocked(workspaceApi.getOsVaultCheck).mockResolvedValue({
      fields: [{ field: "cgpa", outcome: "differs" }, { field: "scale", outcome: "same" }], note: NOTE });
    render(<DocumentConfirm document={doc} onConfirm={() => {}} options={ON} />);
    await screen.findByText(NOTE);
    expect(screen.getAllByText(NOTE)).toHaveLength(1);
    expect(screen.getByTestId("differs-cgpa")).toBeTruthy();
    expect(screen.queryByTestId("differs-scale")).toBeNull();
    expect(workspaceApi.getOsVaultCheck).toHaveBeenCalledWith(4);
  });

  it("a 404 vault-check shows nothing", async () => {
    on();
    vi.mocked(workspaceApi.getOsVaultCheck).mockRejectedValue(new Error("API 404: nothing to compare with"));
    const { container } = render(<DocumentConfirm document={doc} onConfirm={() => {}} options={ON} />);
    await waitFor(() => expect(workspaceApi.getOsVaultCheck).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 20));
    expect(container.querySelector("[data-testid^=differs-]")).toBeNull();
    expect(container.textContent).not.toContain("different value");
  });

  it("with one_upload off it asks for nothing", async () => {
    render(<DocumentConfirm document={doc} onConfirm={() => {}} />);
    await new Promise((r) => setTimeout(r, 20));
    expect(workspaceApi.getOsVaultCheck).not.toHaveBeenCalled();
  });

  it("never fetches the options itself, and links the marker to its input", async () => {
    vi.mocked(workspaceApi.getOsVaultCheck).mockResolvedValue({ fields: [{ field: "cgpa", outcome: "differs" }], note: NOTE });
    render(<DocumentConfirm document={doc} onConfirm={() => {}} options={ON} />);
    const marker = await screen.findByTestId("differs-cgpa");
    expect(workspaceApi.getUploadOptions).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Cgpa", { exact: false }).getAttribute("aria-describedby")).toContain(marker.id);
  });
});
