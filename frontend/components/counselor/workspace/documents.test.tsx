// @vitest-environment jsdom
// req: R-01
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { DocumentsView } from "./documents";
import { workspaceApi } from "@/lib/api";
import copy from "./copy.json";

const enqueueUploads = vi.fn();
const state: { selectedFileId: string | null; files: unknown[] } = { selectedFileId: null, files: [] };
vi.mock("@/lib/workspace-context", () => ({
  useWorkspace: () => ({ selectedFileId: state.selectedFileId, files: state.files, setSelectedFileId: vi.fn(), enqueueUploads, currentFilePath: "" }),
}));
vi.mock("@/components/layout/layout-context", () => ({
  useLayout: () => ({ mobilePane: "list", openMobileList: vi.fn(), filesSection: "files" }),
}));
vi.mock("@/components/files/trash-view", () => ({ TrashView: () => null }));
vi.mock("@/components/os/vault-strip", () => ({ OsVaultStrip: () => null }));
vi.mock("@/lib/api", () => ({ workspaceApi: { getUploadOptions: vi.fn(), registerOsDocument: vi.fn() } }));

const TEXT = { type_label: "What is this document?", type_none: "Something else", registered: "r", consent_needed: "c",
  duplicate: "d", unknown_type: "u", not_readable: "n", not_now: "x" };
const ON = { one_upload: true as const, doc_types: [{ key: "passport", label: "Passport" }, { key: "transcript", label: "Transcript" }], text: TEXT };

afterEach(() => { cleanup(); vi.clearAllMocks(); state.selectedFileId = null; state.files = []; });
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

  it("resets the type after a file is queued, so a second file is not typed by accident", async () => {
    vi.mocked(workspaceApi.getUploadOptions).mockResolvedValue(ON);
    const { container } = view();
    await screen.findByText(TEXT.type_label);
    fireEvent.change(container.querySelector("select")!, { target: { value: "passport" } });
    pick(container);
    expect((container.querySelector("select") as HTMLSelectElement).value).toBe("");
    pick(container);
    expect(enqueueUploads).toHaveBeenLastCalledWith(expect.any(Array), "", undefined);
  });

  it("something else sends no doc_type", async () => {
    vi.mocked(workspaceApi.getUploadOptions).mockResolvedValue(ON);
    const { container } = view();
    await screen.findByText(TEXT.type_label);
    pick(container);
    expect(enqueueUploads).toHaveBeenCalledWith(expect.any(Array), "", undefined);
  });

  it("allows one file per upload once a type is picked, and many with no type", async () => {
    vi.mocked(workspaceApi.getUploadOptions).mockResolvedValue(ON);
    const { container } = view();
    await screen.findByText(TEXT.type_label);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input.multiple).toBe(true);
    fireEvent.change(container.querySelector("select")!, { target: { value: "passport" } });
    expect(input.multiple).toBe(false);
  });

  describe("Let PAI read this", () => {
    const FILE = { id: "f1", filename: "a.pdf", contentType: "application/pdf", size: 1, uploadedBy: "human:s", channelName: null,
      status: "active", createdAt: null };
    const open = (file: Record<string, unknown> = FILE) => { state.selectedFileId = file.id as string; state.files = [file]; };

    it("is shown for an existing untyped file when the one upload is on, and registers it with the picked type", async () => {
      open();
      vi.mocked(workspaceApi.getUploadOptions).mockResolvedValue(ON);
      vi.mocked(workspaceApi.registerOsDocument).mockResolvedValue({ id: 5, status: "reading", note: "PAI is reading it." });
      view();
      const button = await screen.findByRole("button", { name: copy.documents.readThis }) as HTMLButtonElement;
      expect(button.disabled).toBe(true);  // a type first
      fireEvent.change(screen.getByLabelText(copy.documents.readThisType), { target: { value: "transcript" } });
      fireEvent.click(button);
      expect(await screen.findByText("PAI is reading it.")).toBeTruthy();
      expect(workspaceApi.registerOsDocument).toHaveBeenCalledWith("f1", "transcript");
      expect(screen.queryByRole("button", { name: copy.documents.readThis })).toBeNull();
    });

    it("shows the server's refusal note and keeps the action", async () => {
      open();
      vi.mocked(workspaceApi.getUploadOptions).mockResolvedValue(ON);
      vi.mocked(workspaceApi.registerOsDocument).mockResolvedValue({ refused: "consent_needed", note: "Agree to the terms first." });
      view();
      await screen.findByRole("button", { name: copy.documents.readThis });
      fireEvent.change(screen.getByLabelText(copy.documents.readThisType), { target: { value: "passport" } });
      fireEvent.click(screen.getByRole("button", { name: copy.documents.readThis }));
      expect(await screen.findByText("Agree to the terms first.")).toBeTruthy();
      expect(screen.getByRole("button", { name: copy.documents.readThis })).toBeTruthy();
    });

    it("is not shown with the part off, for a typed file, an agent's file or a file PAI cannot read", async () => {
      open();
      vi.mocked(workspaceApi.getUploadOptions).mockResolvedValue({ one_upload: false });
      const off = view();
      await waitFor(() => expect(workspaceApi.getUploadOptions).toHaveBeenCalled());
      expect(screen.queryByRole("button", { name: copy.documents.readThis })).toBeNull();
      expect(off.container.querySelectorAll("select").length).toBe(0);
      cleanup();
      vi.mocked(workspaceApi.getUploadOptions).mockResolvedValue(ON);
      for (const other of [{ ...FILE, os_document: { id: 1, status: "x", note: "n" } }, { ...FILE, uploadedBy: "openagents:x" },
        { ...FILE, contentType: "text/plain" }]) {
        open(other);
        view();
        await screen.findByText(TEXT.type_label);
        expect(screen.queryByRole("button", { name: copy.documents.readThis })).toBeNull();
        cleanup();
      }
    });
  });
});
