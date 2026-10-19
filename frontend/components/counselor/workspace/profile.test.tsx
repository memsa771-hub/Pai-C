// @vitest-environment jsdom
import { it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup, within } from "@testing-library/react";
import { LivingProfile, EvidenceCard, CoverageHeatmap, CertaintyChart } from "./profile";
import { workspaceApi } from "@/lib/api";
import { picture, cards } from "@/tests/fixtures/counselor";
vi.mock("@/lib/api", () => ({
  workspaceApi: {
    getCounselorWorkspace: vi.fn(),
    getProfileCards: vi.fn(),
    reviewProfileCard: vi.fn(),
  },
}));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  window.history.replaceState({}, "", "/");
});
const RAW_KEY = /\b(?:identity|location|preferences)\.[a-z_]+\b|\b[a-z]{2,}_[a-z_]{2,}\b/;
it("renders the visual profile without interpretation scores or private notes", async () => {
  vi.mocked(workspaceApi.getCounselorWorkspace).mockResolvedValue(picture);
  vi.mocked(workspaceApi.getProfileCards).mockResolvedValue({ cards });
  render(<LivingProfile onChat={vi.fn()} />);
  expect(await screen.findByRole("heading", { level: 1, name: "Sam Taylor" })).toBeTruthy();
  for (const title of [
    "How PAI sees you",
    "What PAI understands so far",
    "Your certainty over time",
    "What you enjoy",
    "What you are good at",
    "People around you",
    "Your education",
    "PAI still wants to know",
  ])
    expect(screen.getByRole("heading", { name: title })).toBeTruthy();
  const text = document.body.textContent || "";
  expect(text).not.toContain("private_notes");
  expect(text).not.toMatch(/\d+\s?%\s?(understood|known|complete)/i);
  expect(text).not.toMatch(RAW_KEY);
  // Worries are private until the student asks to see them.
  expect(text).not.toContain("Financial security");
  fireEvent.click(screen.getByRole("button", { name: "Show private details" }));
  expect(document.body.textContent).toContain("Financial security");
});
it("explains that an area can have saved evidence and still invite deeper discussion", async () => {
  vi.mocked(workspaceApi.getCounselorWorkspace).mockResolvedValue({
    ...picture,
    coverage: { ...picture.coverage, history: { covered: false, item_count: 1 } },
  });
  vi.mocked(workspaceApi.getProfileCards).mockResolvedValue({ cards });
  const chat = vi.fn();
  render(<LivingProfile onChat={chat} />);
  fireEvent.click(await screen.findByRole("button", {
    name: "Education & experience · Some details saved; explore further",
  }));
  expect(chat).toHaveBeenCalledWith("Education & experience");
});
it("tapping a heatmap area opens readable details filtered to that area", async () => {
  vi.mocked(workspaceApi.getCounselorWorkspace).mockResolvedValue(picture);
  vi.mocked(workspaceApi.getProfileCards).mockResolvedValue({ cards });
  render(<LivingProfile onChat={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: /^Education & experience: Shown/ }));
  expect(screen.getByRole("tab", { name: "Details" }).getAttribute("aria-selected")).toBe("true");
  expect(screen.getByText("Showing: Education & experience")).toBeTruthy();
  expect(screen.getAllByText("Qualification").length).toBeGreaterThan(0);
  expect(screen.queryByText("Name")).toBeNull();
  expect(document.body.textContent).not.toMatch(RAW_KEY);
});
it("confirms the exact digest; edits require an explanation", async () => {
  const done = vi.fn();
  render(<ul><EvidenceCard card={cards[0]} onSaved={done} /></ul>);
  fireEvent.click(screen.getByRole("button", { name: "Show source and actions for Name" }));
  expect(screen.getByText(/You confirmed this on/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
  await waitFor(() =>
    expect(workspaceApi.reviewProfileCard).toHaveBeenCalledWith(
      cards[0],
      expect.objectContaining({ action: "confirm", expected_digest: cards[0].digest }),
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Name" }), { target: { value: "New name" } });
  const save = screen.getByRole("button", { name: "Save" }) as HTMLButtonElement;
  expect(save.disabled).toBe(true);
  fireEvent.change(screen.getByRole("textbox", { name: "What should PAI know about this correction?" }), {
    target: { value: "Correct spelling" },
  });
  fireEvent.click(save);
  await waitFor(() =>
    expect(workspaceApi.reviewProfileCard).toHaveBeenLastCalledWith(
      cards[0],
      expect.objectContaining({ action: "edit", value: "New name", text: "Correct spelling" }),
    ),
  );
});
it.each(["light", "dark"])("labels evidence in words, not colour alone, in %s", (theme) => {
  const { container } = render(
    <div className={theme}>
      <CoverageHeatmap coverage={picture.coverage} />
      <CertaintyChart ratings={picture.ratings} />
    </div>,
  );
  const areas = within(screen.getByRole("list", { name: "What PAI understands so far" })).getAllByRole("button");
  expect(areas).toHaveLength(10);
  expect(areas[0].getAttribute("aria-label")).toMatch(/^Current life: Confirmed, 2 pieces of evidence/);
  expect(areas[9].getAttribute("aria-label")).toMatch(/^Options & myths: Not yet, 0 pieces of evidence/);
  expect(screen.getByRole("img", { name: /Your certainty over time/ })).toBeTruthy();
  expect(container).toMatchSnapshot();
});
