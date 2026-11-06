// @vitest-environment jsdom
// req: R-01
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { DocumentsView } from "./documents";
import { workspaceApi } from "@/lib/api";
import copy from "./copy.json";

const enqueueUploads = vi.fn();
vi.mock("@/lib/workspace-context", () => ({
  useWorkspace: () => ({ selectedFileId: null, setSelectedFileId: vi.fn(), enqueueUploads, currentFilePath: "" }),
}));
vi.mock("@/components/layout/layout-context", () => ({
  useLayout: () => ({ mobilePane: "list", openMobileList: vi.fn(), filesSection: "files" }),
}));
vi.mock("@/components/files/trash-view", () => ({ TrashView: () => null }));
vi.mock("@/components/os/vault-strip", () => ({ OsVaultStrip: () => null }));
vi.mock("@/lib/api", () => ({ workspaceApi: { getUploadOptions: vi.fn() } }));

const TEXT = { type_label: "What is this document?", type_none: "Something else", registered: "r", consent_needed: "c",
  duplicate: "d", unknown_type: "u", not_readable: "n", not_now: "x" };
const ON = { one_upload: true as const, doc_types: [{ key: "passport", label: "Passport" }, { key: "transcript", label: "Transcript" }], text: TEXT };

afterEach(() => { cleanup(); vi.clearAllMocks(); });
const view = () => render(<DocumentsView list={<p>list</p>} preview={<p>preview</p>} />);
const pick = (container: HTMLElement) => {
  const input = container.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [new File(["x"], "a.pdf", { type: "application/pdf" })] } });
};

describe("documents view", () => {
  it("shows the type picker only when one_upload", async () => {
    vi.mocked(workspaceApi.getUploadOptions).mockResolvedValue({ one_upload: false });
    const off = view();
    await waitFor(() => expect(workspaceApi.getUploadOptions).toHaveBeenCalled());
    expect(off.container.querySelector("select")).toBeNull();
    cleanup();
    vi.mocked(workspaceApi.getUploadOptions).mockResolvedValue(ON);
    view();
    expect(await screen.findByText(TEXT.type_label)).toBeTruthy();
    expect(screen.getByRole("option", { name: TEXT.type_none })).toBeTruthy();
    expect(screen.getByRole("option", { name: "Passport" })).toBeTruthy();
  });

  it("with one_upload off the header row is today's: the title and the one upload button", async () => {
    vi.mocked(workspaceApi.getUploadOptions).mockResolvedValue({ one_upload: false });
    const { container } = view();
    await waitFor(() => expect(workspaceApi.getUploadOptions).toHaveBeenCalled());
    const row = container.querySelector("h1")!.parentElement!;
    expect(Array.from(row.children).map((c) => c.tagName)).toEqual(["H1", "INPUT", "BUTTON"]);
    expect(row.textContent).toBe(`${copy.documentsTitle}${copy.documents.upload}`);
  });

  it("upload with the picked type passes it on", async () => {
    vi.mocked(workspaceApi.getUploadOptions).mockResolvedValue(ON);
    const { container } = view();
    await screen.findByText(TEXT.type_label);
    fireEvent.change(container.querySelector("select")!, { target: { value: "passport" } });
    pick(container);
    expect(enqueueUploads).toHaveBeenCalledWith(expect.any(Array), "", "passport");
  });

  it("something else sends no doc_type", async () => {
    vi.mocked(workspaceApi.getUploadOptions).mockResolvedValue(ON);
    const { container } = view();
    await screen.findByText(TEXT.type_label);
    pick(container);
    expect(enqueueUploads).toHaveBeenCalledWith(expect.any(Array), "", undefined);
  });
});
