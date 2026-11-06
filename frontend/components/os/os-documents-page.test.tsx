// @vitest-environment jsdom
// req: R-01
import { Suspense } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { I18nProvider } from "@/lib/i18n";
import { workspaceApi } from "@/lib/api";
import OsDocumentsPage from "../../app/[workspaceId]/(os)/os-documents/page";

vi.mock("@/lib/config", () => ({ OS_UI_ENABLED: true, OS_REHEARSAL_UI: false, OS_FROM_STAGE: "H" }));
vi.mock("@/lib/pai-auth-context", () => ({ usePaiAuth: () => ({ loading: false, user: { uid: "u" }, idToken: "t" }) }));
vi.mock("next/navigation", () => ({ useParams: () => ({ workspaceId: "ws1" }), useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/ws1/os-documents", notFound: vi.fn() }));
vi.mock("@/components/os/os-header", () => ({ OsHeader: () => null }));
vi.mock("@/lib/api", () => ({ workspaceApi: {
  configure: vi.fn(), getOsDocuments: vi.fn(), getOsConsent: vi.fn(), getUploadOptions: vi.fn(),
  uploadFile: vi.fn(), uploadOsDocument: vi.fn(), agreeOsConsent: vi.fn(),
} }));

const params = Object.assign(Promise.resolve({ workspaceId: "ws1" }), { status: "fulfilled", value: { workspaceId: "ws1" } });
const TEXT = { type_label: "a", type_none: "b", registered: "c", consent_needed: "d", duplicate: "e", unknown_type: "f", not_readable: "g", not_now: "h" };
const TERMS = { version: 1, agreed: false, text: "Pilot terms text.", agreed_at: null };

function setup(one: boolean, agreed = true) {
  vi.mocked(workspaceApi.getOsDocuments).mockResolvedValue({ documents: [], findings: [], doc_types: [{ key: "passport", label: "Passport" }] });
  vi.mocked(workspaceApi.getOsConsent).mockResolvedValue({ ...TERMS, agreed } as never);
  vi.mocked(workspaceApi.getUploadOptions).mockResolvedValue(one
    ? { one_upload: true, doc_types: [{ key: "passport", label: "Passport" }], text: TEXT } : { one_upload: false });
  const r = render(<I18nProvider><Suspense fallback={null}><OsDocumentsPage params={params} /></Suspense></I18nProvider>);
  return r;
}
async function pick(container: HTMLElement) {
  await waitFor(() => expect(workspaceApi.getUploadOptions).toHaveBeenCalled());
  await new Promise((r) => setTimeout(r, 20));
  const input = await waitFor(() => { const i = container.querySelector('input[type="file"]'); if (!i) throw new Error("no input"); return i as HTMLInputElement; });
  fireEvent.change(input, { target: { files: [new File(["x"], "p.pdf", { type: "application/pdf" })] } });
}
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("os documents page", () => {
  it("uploads through /v1/files when one_upload", async () => {
    vi.mocked(workspaceApi.uploadFile).mockResolvedValue({ os_document: { id: 1, status: "uploaded", note: "r" } } as never);
    const { container } = setup(true);
    await pick(container);
    await waitFor(() => expect(workspaceApi.uploadFile).toHaveBeenCalled());
    expect(vi.mocked(workspaceApi.uploadFile).mock.calls[0][2]).toEqual({ docType: "passport" });
    expect(workspaceApi.uploadOsDocument).not.toHaveBeenCalled();
  });

  it("with one_upload off it calls uploadOsDocument as today", async () => {
    vi.mocked(workspaceApi.uploadOsDocument).mockResolvedValue({} as never);
    const { container } = setup(false);
    await pick(container);
    await waitFor(() => expect(workspaceApi.uploadOsDocument).toHaveBeenCalled());
    expect(workspaceApi.uploadFile).not.toHaveBeenCalled();
  });

  it("a refused registration shows the backend note", async () => {
    const note = "Saved. PAI cannot read this kind of document yet.";
    vi.mocked(workspaceApi.uploadFile).mockResolvedValue({ os_document: { refused: "unknown_type", note } } as never);
    const { container } = setup(true);
    await pick(container);
    expect((await screen.findByRole("alert")).textContent).toBe(note);
  });

  it("consent_needed shows the consent card", async () => {
    vi.mocked(workspaceApi.uploadFile).mockResolvedValue(
      { os_document: { refused: "consent_needed", note: "Saved. To let PAI read it, first agree." } } as never);
    // consent starts agreed (card hidden); the refusal makes the page ask again and the terms are now unagreed
    vi.mocked(workspaceApi.getOsConsent).mockResolvedValueOnce({ ...TERMS, agreed: true } as never)
      .mockResolvedValue({ ...TERMS, agreed: false } as never);
    vi.mocked(workspaceApi.getOsDocuments).mockResolvedValue({ documents: [], findings: [], doc_types: [{ key: "passport", label: "Passport" }] });
    vi.mocked(workspaceApi.getUploadOptions).mockResolvedValue({ one_upload: true, doc_types: [], text: TEXT });
    const { container } = render(<I18nProvider><Suspense fallback={null}><OsDocumentsPage params={params} /></Suspense></I18nProvider>);
    await pick(container);
    expect(await screen.findByText(/Pilot terms text/)).toBeTruthy();
  });
});
