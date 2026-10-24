// @vitest-environment jsdom
import { it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup, within } from "@testing-library/react";
import { LivingProfile, CoverageHeatmap, CertaintyChart } from "./profile";
import { EvidenceBadge, vaultBadgeLabel } from "@/components/pai";
import { workspaceApi } from "@/lib/api";
import { picture, vault, vaultCatalog } from "@/tests/fixtures/counselor";
const setSelectedFileId = vi.fn();
vi.mock("@/lib/workspace-context", () => ({ useWorkspace: () => ({ setSelectedFileId }) }));
vi.mock("@/lib/api", () => ({
  workspaceApi: {
    getCounselorWorkspace: vi.fn(),
    getVault: vi.fn(),
    getVaultCatalog: vi.fn(),
    addVaultEntry: vi.fn(),
    editVaultEntry: vi.fn(),
    confirmVaultEntry: vi.fn(),
    removeVaultEntry: vi.fn(),
    resolveVaultConflict: vi.fn(),
  },
}));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  window.history.replaceState({}, "", "/");
});
const RAW_KEY = /\b(?:identity|location|preferences)\.[a-z_]+\b|\b[a-z]{2,}_[a-z_]{2,}\b/;
function setup(view = vault) {
  vi.mocked(workspaceApi.getCounselorWorkspace).mockResolvedValue(picture);
  vi.mocked(workspaceApi.getVault).mockResolvedValue(view);
  vi.mocked(workspaceApi.getVaultCatalog).mockResolvedValue(vaultCatalog);
  for (const write of ["addVaultEntry", "editVaultEntry", "confirmVaultEntry", "removeVaultEntry"] as const)
    vi.mocked(workspaceApi[write]).mockResolvedValue({ saved: true, kind: "fact", type: "x", id: "new" });
  vi.mocked(workspaceApi.resolveVaultConflict).mockResolvedValue({ resolved: true });
  const chat = vi.fn(), navigate = vi.fn();
  render(<LivingProfile onChat={chat} onNavigate={navigate} />);
  return { chat, navigate };
}
const field = (label: string) => screen.getByRole("button", { name: new RegExp(`^Show source and actions for ${label}: `) });
async function openField(label: string, value = "") {
  fireEvent.click(await screen.findByRole("button", { name: new RegExp(`^Show source and actions for ${label}: ${value}`) }));
  return screen.findByRole("dialog");
}

it("reads Details from the Vault: sections, badges, document links, re-check markers and missing basics", async () => {
  const { chat, navigate } = setup();
  expect(await screen.findByRole("heading", { level: 1, name: "Sam Taylor" })).toBeTruthy();
  // The current education's qualification and the city come from Vault entries.
  expect(screen.getByText("Secondary education · My city")).toBeTruthy();
  expect(screen.getByRole("img", { name: /\d+% complete/ })).toBeTruthy();
  for (const title of ["About you", "Education", "Tests", "Missing details"])
    expect(screen.getByRole("heading", { name: title })).toBeTruthy();
  // Empty sections outside alwaysShow stay out of the way.
  expect(screen.queryByRole("heading", { name: "Documents" })).toBeNull();
  // Every badge is a word, and "In question" overrides the level.
  expect(field("Full name").textContent).toContain("Confirmed");
  expect(field("Date of birth").textContent).toContain("PAI's guess");
  expect(field("Current country").textContent).toContain("In question");
  expect(field("Current city").textContent).toContain("Stated");
  // Choice codes read as catalog labels.
  expect(screen.getAllByRole("button", { name: /^Show source and actions for Education: Matric/ })).toHaveLength(1);
  expect(within(screen.getByRole("region", { name: "Education" })).getAllByText("From document")).toHaveLength(2);
  // A stale value carries a quiet marker, in words.
  expect(field("Current city").getAttribute("aria-label")).toContain("Check this is still right");
  expect(screen.getAllByText("Check this is still right")).toHaveLength(1);
  // A document link opens Documents with that file selected.
  fireEvent.click(screen.getByRole("button", { name: "Open Result card.jpg" }));
  expect(setSelectedFileId).toHaveBeenCalledWith("result-card");
  expect(navigate).toHaveBeenCalledWith("files");
  // Missing basics are recomputed from entries and hand PAI a draft.
  const missing = screen.getByRole("complementary", { name: "Missing details" });
  expect(within(missing).getByText("Gender")).toBeTruthy();
  expect(within(missing).queryByText("Your name")).toBeNull();
  fireEvent.click(within(missing).getAllByRole("button", { name: /Add with PAI/ })[0]);
  expect(chat).toHaveBeenCalledWith(expect.stringMatching(/^I want to add my /));
  // Marks only said invite a result card.
  const proof = screen.getByRole("region", { name: "Confirm with a document" });
  expect(within(proof).getByText("Practice aptitude test")).toBeTruthy();
  expect(document.body.textContent).not.toMatch(RAW_KEY);
});

it("offers an empty always-shown section to PAI", async () => {
  const { chat } = setup({ ...vault, details: { ...vault.details, tests: { label: "Tests", entries: [] } } });
  const tests = await screen.findByRole("region", { name: "Tests" });
  fireEvent.click(within(tests).getByRole("button", { name: /Add with PAI/ }));
  expect(chat).toHaveBeenCalledWith("I want to add a test or exam result.");
});

it("shows only the answers each conflict card offers, four or two", async () => {
  setup();
  const check = await screen.findByRole("region", { name: "Please check" });
  const [city, owner] = within(check).getAllByRole("listitem");
  expect(within(city).getByText("Which current city is right?")).toBeTruthy();
  expect(within(city).getByText("Saved: Islamabad. New: Lahore.")).toBeTruthy();
  expect(within(city).getAllByRole("button").map((b) => b.textContent)).toEqual(
    ["Keep Islamabad", "Use Lahore", "Both were true at different times", "Neither, I'll write it"]);
  expect(within(owner).getAllByRole("button").map((b) => b.textContent)).toEqual(["Keep Sam Taylor", "Use Alex Doe"]);
  fireEvent.click(within(city).getByRole("button", { name: "Use Lahore" }));
  await waitFor(() => expect(workspaceApi.resolveVaultConflict).toHaveBeenCalledWith("c-city", "accept_proposed", undefined));
});

it("lets the student write the right answer when neither is", async () => {
  setup();
  const check = await screen.findByRole("region", { name: "Please check" });
  const [city] = within(check).getAllByRole("listitem");
  fireEvent.click(within(city).getByRole("button", { name: "Neither, I'll write it" }));
  fireEvent.change(within(city).getByRole("textbox", { name: "The right answer" }), { target: { value: "Karachi" } });
  fireEvent.click(within(city).getByRole("button", { name: "Save" }));
  await waitFor(() => expect(workspaceApi.resolveVaultConflict).toHaveBeenCalledWith("c-city", "provide_new", "Karachi"));
});

it("confirms, edits and removes through the Vault API", async () => {
  setup();
  let dialog = await openField("Full name");
  expect(within(dialog).getByText(/^You confirmed this on/)).toBeTruthy();
  fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
  await waitFor(() => expect(workspaceApi.confirmVaultEntry).toHaveBeenCalledWith("fact", "name"));

  dialog = await openField("Full name");
  fireEvent.click(within(dialog).getByRole("button", { name: "Edit" }));
  const save = within(dialog).getByRole("button", { name: "Save" }) as HTMLButtonElement;
  expect(save.disabled).toBe(true);
  fireEvent.change(within(dialog).getByRole("textbox", { name: "Full name" }), { target: { value: "New name" } });
  fireEvent.click(save);
  await waitFor(() => expect(workspaceApi.editVaultEntry).toHaveBeenCalledWith("fact", "name", "New name"));

  dialog = await openField("Full name");
  fireEvent.click(within(dialog).getByRole("button", { name: "Remove" }));
  fireEvent.click(within(dialog).getByRole("button", { name: "Yes, remove it" }));
  await waitFor(() => expect(workspaceApi.removeVaultEntry).toHaveBeenCalledWith("fact", "name"));
});

it("shows the backend's own message when an edit is refused", async () => {
  setup();
  vi.mocked(workspaceApi.editVaultEntry).mockRejectedValue(
    new Error('API 400: {"code":400,"message":"Household income is not saved here.","data":null}'));
  const dialog = await openField("Current city");
  fireEvent.click(within(dialog).getByRole("button", { name: "Edit" }));
  fireEvent.change(within(dialog).getByRole("textbox", { name: "Current city" }), { target: { value: "Elsewhere" } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
  expect((await within(dialog).findByRole("alert")).textContent).toBe("Household income is not saved here.");
});

it("explains where a value came from, what disagrees, and links the documents", async () => {
  const { navigate } = setup();
  let dialog = await openField("Date of birth");
  expect(within(dialog).getByText(/^PAI's guess from your conversation on .*2026$/)).toBeTruthy();
  fireEvent.keyDown(dialog, { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

  dialog = await openField("Education", "Matric");
  expect(within(dialog).getByText("Matric")).toBeTruthy();
  expect(within(dialog).getByText("A document says 79")).toBeTruthy();
  fireEvent.click(within(dialog).getByRole("button", { name: "Open Old card.pdf" }));
  expect(setSelectedFileId).toHaveBeenCalledWith("old-card");
  expect(navigate).toHaveBeenCalledWith("files");
});

it("builds Background from the Mirror and the Vault story, and adds a story item", async () => {
  window.history.replaceState({}, "", "/?tab=background");
  const { chat } = setup();
  expect(await screen.findByRole("heading", { name: "How PAI sees you" })).toBeTruthy();
  for (const title of ["Your story", "Interest", "Family member", "Pressure"])
    expect(screen.getByRole("heading", { name: title })).toBeTruthy();
  expect(document.body.textContent).toContain("Financial security");
  expect(screen.getByText("What weighs on your choice?")).toBeTruthy();
  expect(screen.getByRole("button", { name: /^Fixing things/ }).textContent).toContain("Stated");

  fireEvent.click(screen.getByRole("button", { name: "Talk about this: Interest" }));
  expect(chat).toHaveBeenCalledWith("Can we talk about interest?");

  fireEvent.click(screen.getByRole("button", { name: "Add to Interest" }));
  const form = screen.getByRole("form", { name: "Add to Interest" });
  const add = within(form).getByRole("button", { name: "Add" }) as HTMLButtonElement;
  expect(add.disabled).toBe(true);
  const [text, example] = within(form).getAllByRole("textbox");
  expect(example.closest("label")?.textContent).toContain("(optional)");
  fireEvent.change(text, { target: { value: "Drawing" } });
  fireEvent.click(add);
  await waitFor(() => expect(workspaceApi.addVaultEntry).toHaveBeenCalledWith("interest", { text: "Drawing" }));
  expect(document.body.textContent).not.toMatch(RAW_KEY);
});

it("adds a story item with catalog choices and opens an entry's review", async () => {
  window.history.replaceState({}, "", "/?tab=background");
  setup();
  fireEvent.click(await screen.findByRole("button", { name: "Add to Family member" }));
  const form = screen.getByRole("form", { name: "Add to Family member" });
  const relation = within(form).getByRole("combobox", { name: "Relationship" }) as HTMLSelectElement;
  expect([...relation.options].map((o) => o.textContent)).toEqual(["Choose", "Father", "Mother"]);
  fireEvent.change(relation, { target: { value: "father" } });
  fireEvent.click(within(form).getByRole("checkbox"));
  fireEvent.click(within(form).getByRole("button", { name: "Add" }));
  await waitFor(() => expect(workspaceApi.addVaultEntry).toHaveBeenCalledWith("family_member", { relation: "father", lives_with: true }));

  fireEvent.click(screen.getByRole("button", { name: /^Fixing things/ }));
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByRole("heading", { name: "Interest" })).toBeTruthy();
  fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
  await waitFor(() => expect(workspaceApi.confirmVaultEntry).toHaveBeenCalledWith("item", "fixing"));
});

it("names PAI's guess and an open question with an icon and a word", () => {
  render(<div><EvidenceBadge level="inferred" label={vaultBadgeLabel("inferred")} /><EvidenceBadge level="question" label={vaultBadgeLabel("question")} /><EvidenceBadge level="shown" label={vaultBadgeLabel("shown")} /></div>);
  for (const word of ["PAI's guess", "In question", "From document"]) {
    const badge = screen.getByText(word).parentElement!;
    expect(badge.querySelector("svg")).toBeTruthy();
  }
  // Existing callers keep the ladder's own words.
  cleanup();
  render(<EvidenceBadge level="shown" />);
  expect(screen.getByText("Shown")).toBeTruthy();
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
