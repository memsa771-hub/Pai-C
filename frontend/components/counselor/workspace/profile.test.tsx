// @vitest-environment jsdom
import { it, expect, vi, afterEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  cleanup,
} from "@testing-library/react";
import {
  LivingProfile,
  EvidenceCard,
  CoverageWheel,
  CertaintyChart,
} from "./profile";
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
});
it("renders all public profile sections without interpretation scores", async () => {
  vi.mocked(workspaceApi.getCounselorWorkspace).mockResolvedValue(picture);
  vi.mocked(workspaceApi.getProfileCards).mockResolvedValue({ cards });
  render(<LivingProfile onChat={vi.fn()} />);
  expect(await screen.findByText("A living picture of you")).toBeTruthy();
  for (const title of [
    "Who I am",
    "Education timeline",
    "People around me",
    "Interests",
    "Strengths & capabilities",
    "Values",
    "Pressures & limits",
    "Options you know & myths to check",
    "Goals & whose wish",
    "PAI still wants to know",
  ])
    expect(screen.getByRole("heading", { name: title })).toBeTruthy();
  expect(document.body.textContent).not.toContain("private_notes");
  expect(
    screen
      .getByRole("img", { name: "What PAI knows so far" })
      .querySelectorAll("path"),
  ).toHaveLength(10);
});
it("confirms the exact digest; edits require an explanation", async () => {
  const done = vi.fn();
  render(<EvidenceCard card={cards[0]} onSaved={done} />);
  fireEvent.click(screen.getByText("Confirm"));
  await waitFor(() =>
    expect(workspaceApi.reviewProfileCard).toHaveBeenCalledWith(
      cards[0],
      expect.objectContaining({
        action: "confirm",
        expected_digest: cards[0].digest,
      }),
    ),
  );
  fireEvent.click(screen.getByText("Edit"));
  fireEvent.change(
    screen.getByRole("textbox", { name: "identity.full_name" }),
    { target: { value: "New name" } },
  );
  fireEvent.change(
    screen.getByRole("textbox", {
      name: "What should PAI know about this correction?",
    }),
    { target: { value: "Correct spelling" } },
  );
  fireEvent.click(screen.getByText("Save"));
  await waitFor(() =>
    expect(workspaceApi.reviewProfileCard).toHaveBeenLastCalledWith(
      cards[0],
      expect.objectContaining({
        action: "edit",
        value: "New name",
        text: "Correct spelling",
      }),
    ),
  );
});
it.each(["light", "dark"])(
  "keeps evidence and certainty accessible in %s",
  (theme) => {
    const { container } = render(
      <div className={theme}>
        <CoverageWheel coverage={picture.coverage} />
        <CertaintyChart ratings={picture.ratings} />
      </div>,
    );
    expect(container.querySelectorAll("svg")).toHaveLength(2);
    expect(container).toMatchSnapshot();
  },
);
