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
it("shows Details as fields with missing basics, and Background as the Mirror and the student's story", async () => {
  vi.mocked(workspaceApi.getCounselorWorkspace).mockResolvedValue(picture);
  vi.mocked(workspaceApi.getProfileCards).mockResolvedValue({ cards });
  const chat = vi.fn();
  render(<LivingProfile onChat={chat} />);
  expect(await screen.findByRole("heading", { level: 1, name: "Sam Taylor" })).toBeTruthy();
  expect(screen.getByRole("img", { name: /\d+% complete/ })).toBeTruthy();
  for (const title of ["About you", "Education and tests", "Missing details"])
    expect(screen.getByRole("heading", { name: title })).toBeTruthy();
  // A missing basic hands PAI a draft; nothing is saved from here.
  fireEvent.click(screen.getAllByRole("button", { name: /Add with PAI/ })[0]);
  expect(chat).toHaveBeenCalledWith(expect.stringMatching(/^I want to add my /));
  // Opening a field shows its source and the review actions.
  fireEvent.click(screen.getByRole("button", { name: /^Show source and actions for Name/ }));
  expect(await screen.findByRole("dialog")).toBeTruthy();
  expect(within(screen.getByRole("dialog")).getByRole("button", { name: "Confirm" })).toBeTruthy();
  fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
  fireEvent.click(screen.getByRole("tab", { name: "Background" }));
  for (const title of ["How PAI sees you", "Your story", "Interests", "Family"])
    expect(screen.getByRole("heading", { name: title })).toBeTruthy();
  for (const gone of ["What PAI understands so far", "Your certainty over time", "PAI still wants to know"])
    expect(screen.queryByRole("heading", { name: gone })).toBeNull();
  const text = document.body.textContent || "";
  expect(text).not.toContain("private_notes");
  expect(text).not.toMatch(/\d+\s?%\s?(understood|known)/i);
  expect(text).not.toMatch(RAW_KEY);
  // Worries are private until the student asks to see them.
  expect(text).not.toContain("Financial security");
  fireEvent.click(screen.getByRole("button", { name: "Show private details" }));
  expect(document.body.textContent).toContain("Financial security");
});
it("hands a story topic to PAI instead of editing shared evidence here", async () => {
  vi.mocked(workspaceApi.getCounselorWorkspace).mockResolvedValue(picture);
  vi.mocked(workspaceApi.getProfileCards).mockResolvedValue({ cards });
  window.history.replaceState({}, "", "/?tab=background");
  const chat = vi.fn();
  render(<LivingProfile onChat={chat} />);
  fireEvent.click(await screen.findByRole("button", { name: "Talk about this: Interests" }));
  expect(chat).toHaveBeenCalledWith("Can we talk about interests?");
});
it("confirms the exact digest; edits require an explanation", async () => {
  const done = vi.fn();
  render(<ul><EvidenceCard card={cards[0]} onSaved={done} /></ul>);
  // The row's name carries the label, the value and its evidence level.
  fireEvent.click(screen.getByRole("button", { name: /^Show source and actions for Name: Name Sam Taylor Confirmed/ }));
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
