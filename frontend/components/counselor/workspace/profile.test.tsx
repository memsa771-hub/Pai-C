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
    getStudentProfile: vi.fn().mockResolvedValue({ issues: [] }),
    resolveProfileIssue: vi.fn(),
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
  for (const title of ["About you", "Education", "Experience", "Missing details"])
    expect(screen.getByRole("heading", { name: title })).toBeTruthy();
  // No preferred name and nothing masked: only what onboarding asked for.
  expect(screen.queryByText("Preferred name")).toBeNull();
  expect(screen.queryByRole("button", { name: /private details/i })).toBeNull();
  expect(document.body.textContent).not.toContain("Hidden for your privacy");
  // Date of birth from onboarding shows as a readable date, not hidden.
  expect(screen.getByText("Date of birth")).toBeTruthy();
  expect(screen.getByRole("button", { name: /^Show source and actions for Date of birth: .*2008/ })).toBeTruthy();
  // A missing basic hands PAI a draft; nothing is saved from here.
  fireEvent.click(within(screen.getByRole("complementary", { name: "Missing details" })).getAllByRole("button", { name: /Add with PAI/ })[0]);
  expect(chat).toHaveBeenCalledWith(expect.stringMatching(/^I want to add my /));
  // An empty section offers the same way in.
  const experience = screen.getByRole("region", { name: "Experience" });
  fireEvent.click(within(experience).getByRole("button", { name: /Add with PAI/ }));
  expect(chat).toHaveBeenLastCalledWith(expect.stringMatching(/^I want to add an experience/));
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
  // Family hopes and worries read plainly in the student's own story.
  expect(text).toContain("Financial security");
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
it("asks the student to settle a conflict between what they said and their profile", async () => {
  vi.mocked(workspaceApi.getCounselorWorkspace).mockResolvedValue(picture);
  vi.mocked(workspaceApi.getProfileCards).mockResolvedValue({ cards });
  vi.mocked(workspaceApi.getStudentProfile).mockResolvedValue({ issues: [{
    id: "i1", type: "conflicting_fact", severity: "blocking", summary: "", clarificationQuestion: null,
    recordType: null, recordId: null, fieldKey: "location.current_city", values: { current: "Islamabad", proposed: "Lahore" }, createdAt: null,
  }] } as never);
  vi.mocked(workspaceApi.resolveProfileIssue).mockResolvedValue({ resolved: true, action: "accept_proposed", id: "f" });
  render(<LivingProfile onChat={vi.fn()} />);
  const check = await screen.findByRole("region", { name: "Please check" });
  expect(within(check).getByText("Your profile says Islamabad. You also said Lahore.")).toBeTruthy();
  fireEvent.click(within(check).getByRole("button", { name: "Use Lahore" }));
  await waitFor(() => expect(workspaceApi.resolveProfileIssue).toHaveBeenCalledWith("i1", "accept_proposed"));
});
it("invites a result card for marks the student only said", async () => {
  vi.mocked(workspaceApi.getCounselorWorkspace).mockResolvedValue(picture);
  // The live audit's case: FSc marks said in chat, no document yet.
  const fsc = { kind: "education", key: "education", id: "fsc", digest: "e".repeat(64), evidence_level: "stated",
    value: { qualification_name: "FSc Pre-Engineering", result: { marks_obtained: 780, marks_total: 1100 } },
    source: { quote: "780 out of 1100" }, updated_at: "2026-10-21" };
  vi.mocked(workspaceApi.getProfileCards).mockResolvedValue({ cards: [...cards, fsc] } as never);
  const navigate = vi.fn();
  render(<LivingProfile onChat={vi.fn()} onNavigate={navigate} />);
  const proof = await screen.findByRole("region", { name: "Confirm with a document" });
  expect(within(proof).getByText("FSc Pre-Engineering")).toBeTruthy();
  fireEvent.click(within(proof).getByRole("button", { name: "Upload result card" }));
  expect(navigate).toHaveBeenCalledWith("files");
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
