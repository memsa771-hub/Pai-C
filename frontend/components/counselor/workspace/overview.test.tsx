// @vitest-environment jsdom
import { it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, within } from "@testing-library/react";
import { Overview } from "./overview";
import { journeyProgress, type JourneySignals } from "./use-journey";
import { workspaceApi } from "@/lib/api";
import { picture, cards } from "@/tests/fixtures/counselor";
import type { Possibility } from "@/lib/possibilities";
vi.mock("@/lib/api", () => ({ workspaceApi: { getProfileCards: vi.fn() } }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

const path = (id: string, title: string, status: Possibility["status"]) =>
  ({ id, title, why: `Why ${title}`, status, evidence: [], unknowns: [], roadmap_id: null }) as unknown as Possibility;
const data: JourneySignals = {
  picture,
  possibilities: [path("p1", "Practical design", "suggested"), path("p2", "Applied computing", "saved"), path("p3", "Old idea", "dismissed")],
  roadmaps: [],
  decision: null,
};
const journey = { data, error: false, busy: false, refresh: vi.fn(), progress: journeyProgress(data) };

it("shows signals from the student's own data, never a score, and only drafts for PAI", async () => {
  vi.mocked(workspaceApi.getProfileCards).mockResolvedValue({ cards });
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
  // Asking fills a draft in the conversation; nothing is sent from here.
  fireEvent.change(screen.getByLabelText("Ask PAI"), { target: { value: "Is design right for me?" } });
  fireEvent.submit(screen.getByLabelText("Ask PAI").closest("form")!);
  expect(onChat).toHaveBeenCalledWith("Is design right for me?");
  // The recommendation pager moves between real next steps.
  await screen.findByText(/Your profile is missing \d+ details\./, undefined, { timeout: 2000 }).catch(() => null);
  fireEvent.click(screen.getByRole("button", { name: "Next recommendation" }));
  expect(screen.getByText(/^02 \/ 0\d$/)).toBeTruthy();
});
