// @vitest-environment jsdom
import { it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, within, waitFor } from "@testing-library/react";
import { Overview } from "./overview";
import { journeyProgress, type JourneySignals } from "./use-journey";
import { workspaceApi } from "@/lib/api";
import { picture, vault } from "@/tests/fixtures/counselor";
import type { Possibility } from "@/lib/possibilities";
vi.mock("@/lib/api", () => ({ workspaceApi: { getVault: vi.fn() } }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

const path = (id: string, title: string, status: Possibility["status"]) =>
  ({ id, title, why: `Why ${title}`, status, evidence: [], unknowns: [] }) as unknown as Possibility;
const data: JourneySignals = {
  picture,
  possibilities: [path("p1", "Practical design", "suggested"), path("p2", "Applied computing", "saved"), path("p3", "Old idea", "dismissed")],
  placesSearched: false,
  roadmap: null,
};
const journey = { data, error: false, busy: false, refresh: vi.fn(), progress: journeyProgress(data) };

it("shows signals from the student's own data and never a score", async () => {
  vi.mocked(workspaceApi.getVault).mockResolvedValue(vault);
  const navigate = vi.fn(), openPath = vi.fn(), onChat = vi.fn();
  render(<Overview journey={journey} navigate={navigate} openPath={openPath} onChat={onChat} />);
  expect(screen.getByRole("heading", { level: 1, name: "Find the path that fits you." })).toBeTruthy();
  // Dismissed paths do not count.
  expect(screen.getByText("Paths to explore").parentElement?.textContent).toContain("2");
  const paths = screen.getByRole("region", { name: "Your strongest paths" });
  expect(within(paths).queryByText("Old idea")).toBeNull();
  fireEvent.click(within(paths).getByRole("button", { name: /Practical design/ }));
  expect(openPath).toHaveBeenCalledWith("p1");
  expect(document.body.textContent).not.toMatch(/\d+\s?\/\s?100|\d+\s?%\s?(fit|match)/i);
  // The overview has no free-text box; questions belong in the conversation.
  expect(screen.queryByRole("textbox")).toBeNull();
  // The recommendation pager moves between real next steps.
  await screen.findByText(/Your profile is missing \d+ details\./, undefined, { timeout: 2000 }).catch(() => null);
  fireEvent.click(screen.getByRole("button", { name: "Next recommendation" }));
  expect(screen.getByText(/^02 \/ 0\d$/)).toBeTruthy();
});
it("counts Vault entries and the ones the student confirmed", async () => {
  vi.mocked(workspaceApi.getVault).mockResolvedValue(vault);
  render(<Overview journey={journey} navigate={vi.fn()} openPath={vi.fn()} onChat={vi.fn()} />);
  const metric = screen.getByText("Saved in your Vault").parentElement!;
  // Four About entries, two education, one test and two story items; one is confirmed.
  await waitFor(() => expect(metric.textContent).toContain("9"));
  expect(metric.textContent).toContain("1 confirmed by you");
});
it("shows the Mirror picture from the card: who, a few lines, what is unknown, and a link", async () => {
  vi.mocked(workspaceApi.getVault).mockResolvedValue(vault);
  const navigate = vi.fn();
  render(<Overview journey={journey} navigate={navigate} openPath={vi.fn()} onChat={vi.fn()} />);
  const card = screen.getByRole("region", { name: "Your Mirror" });
  expect(within(card).getByText("Sam Taylor")).toBeTruthy();
  expect(within(card).getByText("FSc Pre-Engineering, 78%")).toBeTruthy();
  expect(card.textContent).toContain("You like finding out how machines work.");
  expect(within(card).getByText("2 things still unknown")).toBeTruthy();
  fireEvent.click(within(card).getByRole("button", { name: "Open your Mirror" }));
  expect(navigate).toHaveBeenCalledWith("mirror");
});
it("says PAI needs a little more before the Mirror is ready", async () => {
  vi.mocked(workspaceApi.getVault).mockResolvedValue(vault);
  const early = { ...data, picture: { ...picture, picture: { ...picture.picture!, ready: false, text: null } } };
  render(<Overview journey={{ ...journey, data: early, progress: journeyProgress(early) }} navigate={vi.fn()} openPath={vi.fn()} onChat={vi.fn()} />);
  const card = screen.getByRole("region", { name: "Your Mirror" });
  expect(within(card).getByText("PAI needs a little more to draw your picture.")).toBeTruthy();
});
