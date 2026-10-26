// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup, within } from "@testing-library/react";
import { Roadmap } from "./roadmap";
import { render as renderItem } from "./roadmap-text";
import { workspaceApi } from "@/lib/api";
import { chosenRoute, roadmapCards, roadmapPage } from "@/tests/fixtures/counselor";
import copy from "./copy.json";

vi.mock("@/lib/api", () => ({
  workspaceApi: {
    getRoadmapPage: vi.fn(),
    chooseRoute: vi.fn(),
    setRouteStep: vi.fn(),
    withdrawRoute: vi.fn(),
    getFamilyTalk: vi.fn(),
    prepareFamilyTalk: vi.fn(),
  },
}));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
beforeEach(() => {
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue(roadmapPage);
});
const card = async (title: string) => (await screen.findByRole("heading", { name: title })).closest("article")!;

it("groups the fields with their counts under the education line", async () => {
  render(<Roadmap onNavigate={vi.fn()} />);
  expect(await screen.findByText("From FSc Pre-Engineering, 78%")).toBeTruthy();
  expect(screen.getByText("2 open")).toBeTruthy();
  expect(screen.getByText("1 need a step")).toBeTruthy();
  expect(screen.getByText("1 not open")).toBeTruthy();
  const open = screen.getByRole("region", { name: /You can go/ });
  expect(within(open).getAllByRole("article")).toHaveLength(2);
  expect(within(screen.getByRole("region", { name: /Possible with a step/ })).getAllByRole("article")).toHaveLength(1);
  // Not open is collapsed by default.
  const closed = screen.getByText(/Not open from your group/).closest("details")!;
  expect(closed.open).toBe(false);
  expect(within(closed).getByText("MBBS")).toBeTruthy();
});

it("shows the entry test, the years and the marks rule on a card", async () => {
  render(<Roadmap onNavigate={vi.fn()} />);
  const ee = await card("Electrical Engineering");
  expect(within(ee).getByText("ECAT / NET")).toBeTruthy();
  expect(within(ee).getByText("4 years")).toBeTruthy();
  expect(within(ee).getByText("Needs 60% · you 78%")).toBeTruthy();
  expect(within(ee).getByText("You like finding out how circuits and machines work.")).toBeTruthy();
});

it("notes an uncertain or secondary rule with Check with the university", async () => {
  render(<Roadmap onNavigate={vi.fn()} />);
  expect(within(await card("Pharmacy")).getByText("Check with the university")).toBeTruthy();
  expect(within(await card("Computer Science")).getByText("Check with the university")).toBeTruthy();
  expect(within(await card("Electrical Engineering")).queryByText("Check with the university")).toBeNull();
  expect(within(await card("Pharmacy")).getByText("Biology bridge course at some universities")).toBeTruthy();
});

it("opens a route sheet with the timeline in order and its sources", async () => {
  render(<Roadmap onNavigate={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "See route for Electrical Engineering" }));
  const dialog = await screen.findByRole("dialog");
  const steps = within(dialog).getByRole("list", { name: "Electrical Engineering" }).querySelectorAll(":scope > li");
  expect([...steps].map((li) => li.querySelector("h3")?.textContent)).toEqual(
    ["Now", "What you need", "Entry test", "Degree (4 years)"]);
  expect(within(dialog).getByText("From FSc Pre-Engineering, 78%")).toBeTruthy();
  const source = within(dialog).getByRole("link", { name: /pec\.org\.pk/ });
  expect(source.getAttribute("href")).toBe("https://www.pec.org.pk/regulations.pdf");
  expect(source.getAttribute("target")).toBe("_blank");
  expect(source.getAttribute("rel")).toContain("noopener");
  expect(within(dialog).getByText("Checked October 2026")).toBeTruthy();
  expect((within(dialog).getByRole("button", { name: "Choose this route" }) as HTMLButtonElement).disabled).toBe(false);
});

it("will not choose a field that is not open, and says why", async () => {
  render(<Roadmap onNavigate={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "See route for MBBS" }));
  const dialog = await screen.findByRole("dialog");
  expect((within(dialog).getByRole("button", { name: "Choose this route" }) as HTMLButtonElement).disabled).toBe(true);
  expect(within(dialog).getAllByText("Not open from Pre-Engineering").length).toBeGreaterThan(0);
});

it("compares two or three fields with the same rows for each", async () => {
  render(<Roadmap onNavigate={vi.fn()} />);
  fireEvent.click(await screen.findByRole("checkbox", { name: "Compare Electrical Engineering" }));
  const bar = screen.getByRole("button", { name: "Pick 1 more to compare" }) as HTMLButtonElement;
  expect(bar.disabled).toBe(true);
  fireEvent.click(screen.getByRole("checkbox", { name: "Compare Computer Science" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Compare Pharmacy" }));
  expect((screen.getByRole("checkbox", { name: "Compare MBBS" }) as HTMLInputElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Compare (3)" }));
  const table = within(await screen.findByRole("dialog")).getByRole("table");
  const rows = within(table).getAllByRole("row");
  expect(rows).toHaveLength(1 + Object.keys(copy.roadmap.compareRows).length);
  for (const row of rows) expect(row.children).toHaveLength(4);
  expect(within(table).getAllByRole("rowheader").map((th) => th.textContent)).toEqual(Object.values(copy.roadmap.compareRows));
  // Phones scroll the columns under sticky row labels.
  for (const th of within(table).getAllByRole("rowheader")) expect(th.className).toMatch(/sticky left-0 .*bg-card/);
  expect(within(table).getByText("Bridge or extra courses")).toBeTruthy();
  expect(within(table).getByText("Uncertain")).toBeTruthy();
  expect(within(table).getAllByText("60% · you 78%")).toHaveLength(2);
});

it("joins every need in the compare Extra step cell", async () => {
  const two = { ...roadmapCards[2], verdict: { ...roadmapCards[2].verdict, needs: [
    { kind: "bridge" as const, detail: { text: "Biology bridge" } }, { kind: "marks" as const, detail: { min: 60, have: 55 } }] } };
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue({ ...roadmapPage, fields: [roadmapCards[0], two] });
  render(<Roadmap onNavigate={vi.fn()} />);
  fireEvent.click(await screen.findByRole("checkbox", { name: "Compare Electrical Engineering" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Compare Pharmacy" }));
  fireEvent.click(screen.getByRole("button", { name: "Compare (2)" }));
  const table = within(await screen.findByRole("dialog")).getByRole("table");
  expect(within(table).getByText("Bridge or extra courses, Marks up to 60%")).toBeTruthy();
});

it("tells the shell after choose, tick and withdraw so the journey stage refreshes", async () => {
  const changed = vi.fn();
  vi.mocked(workspaceApi.chooseRoute).mockResolvedValue(chosenRoute);
  render(<Roadmap onNavigate={vi.fn()} onChanged={changed} />);
  fireEvent.click(await screen.findByRole("button", { name: "See route for Pharmacy" }));
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue({ ...roadmapPage, chosen: chosenRoute });
  fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Choose this route" }));
  await waitFor(() => expect(changed).toHaveBeenCalledTimes(1));
  vi.mocked(workspaceApi.setRouteStep).mockResolvedValueOnce({ ...chosenRoute, steps_done: [true, true, false] });
  fireEvent.click(await screen.findByRole("checkbox", { name: "Take University test" }));
  await waitFor(() => expect(changed).toHaveBeenCalledTimes(2));
  vi.mocked(workspaceApi.withdrawRoute).mockResolvedValue(chosenRoute);
  fireEvent.click(screen.getByRole("button", { name: "Change route" }));
  fireEvent.click(screen.getByRole("button", { name: "Yes, change route" }));
  await waitFor(() => expect(changed).toHaveBeenCalledTimes(3));
});

it("chooses a route and shows it at the top with progress", async () => {
  vi.mocked(workspaceApi.chooseRoute).mockResolvedValue(chosenRoute);
  render(<Roadmap onNavigate={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "See route for Pharmacy" }));
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue({ ...roadmapPage, chosen: chosenRoute });
  fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Choose this route" }));
  await waitFor(() => expect(workspaceApi.chooseRoute).toHaveBeenCalledWith("pharmacy"));
  const route = await screen.findByRole("region", { name: "Your route" });
  expect(within(route).getByText("Pharmacy")).toBeTruthy();
  expect(within(route).getByText("1 of 3")).toBeTruthy();
  expect(within(route).getByRole("checkbox", { name: "Take University test" })).toBeTruthy();
});

it("ticks a step through the API and reverts when it fails", async () => {
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue({ ...roadmapPage, chosen: chosenRoute });
  vi.mocked(workspaceApi.setRouteStep).mockResolvedValueOnce({ ...chosenRoute, steps_done: [true, true, false] });
  render(<Roadmap onNavigate={vi.fn()} />);
  const box = (await screen.findByRole("checkbox", { name: "Take University test" })) as HTMLInputElement;
  fireEvent.click(box);
  expect(box.checked).toBe(true); // optimistic
  await waitFor(() => expect(workspaceApi.setRouteStep).toHaveBeenCalledWith(1, true));
  expect(await screen.findByText("2 of 3")).toBeTruthy();
  vi.mocked(workspaceApi.setRouteStep).mockRejectedValueOnce(new Error("offline"));
  const apply = screen.getByRole("checkbox", { name: "Apply for Pharmacy" }) as HTMLInputElement;
  fireEvent.click(apply);
  await waitFor(() => expect(apply.checked).toBe(false));
  expect(screen.getByRole("alert").textContent).toBe(copy.roadmap.error);
});

it("blocks a second tick while a save is in flight, and a failure reverts only its own step", async () => {
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue({ ...roadmapPage, chosen: chosenRoute });
  let fail!: (error: Error) => void;
  vi.mocked(workspaceApi.setRouteStep).mockReturnValueOnce(new Promise((_, reject) => { fail = reject; }));
  render(<Roadmap onNavigate={vi.fn()} />);
  const first = (await screen.findByRole("checkbox", { name: "Biology bridge course at some universities" })) as HTMLInputElement;
  const test = screen.getByRole("checkbox", { name: "Take University test" }) as HTMLInputElement;
  fireEvent.click(test);
  expect(test.checked).toBe(true);
  fireEvent.click(test); // a double click while saving
  fireEvent.click(screen.getByRole("checkbox", { name: "Apply for Pharmacy" }));
  expect(workspaceApi.setRouteStep).toHaveBeenCalledTimes(1);
  fail(new Error("offline"));
  await waitFor(() => expect(test.checked).toBe(false));
  expect(first.checked).toBe(true); // the other ticks stay as they were
  expect(screen.getByRole("alert").textContent).toBe(copy.roadmap.error);
});

it("changes route only after a confirm, and notes a changed situation", async () => {
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue({ ...roadmapPage, chosen: { ...chosenRoute, live_status: "open" } });
  vi.mocked(workspaceApi.withdrawRoute).mockResolvedValue(chosenRoute);
  render(<Roadmap onNavigate={vi.fn()} />);
  expect(await screen.findByText("Your situation changed: now open to you.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Change route" }));
  expect(workspaceApi.withdrawRoute).not.toHaveBeenCalled();
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue(roadmapPage);
  fireEvent.click(screen.getByRole("button", { name: "Yes, change route" }));
  await waitFor(() => expect(workspaceApi.withdrawRoute).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(screen.queryByRole("region", { name: "Your route" })).toBeNull());
});

it("prepares a family talk from the chosen route", async () => {
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue({ ...roadmapPage, chosen: chosenRoute });
  vi.mocked(workspaceApi.getFamilyTalk).mockResolvedValue({
    ready: true, message: "Prepare for your chosen path.", path_id: "path-1",
    family: [{ id: "mother", role: "Mother", wish: "", worry: "The cost", evidence: "She asked about fees." }],
    evidence: [{ id: "e1", quote: "I can get a scholarship." }],
  });
  vi.mocked(workspaceApi.prepareFamilyTalk).mockResolvedValue({ event_id: "ev", script: "Start with the fees." });
  render(<Roadmap onNavigate={vi.fn()} />);
  const region = await screen.findByRole("region", { name: "Your route" });
  expect(workspaceApi.getFamilyTalk).not.toHaveBeenCalled(); // secondary: nothing loads until asked
  const open = within(region).getByRole("button", { name: copy.roadmap.route.family });
  fireEvent.click(open);
  expect(open.getAttribute("aria-expanded")).toBe("true");
  fireEvent.click(await within(region).findByRole("radio", { name: "Mother" }));
  fireEvent.click(within(region).getByRole("checkbox", { name: /scholarship/ }));
  fireEvent.click(within(region).getByRole("button", { name: "Prepare with PAI" }));
  await waitFor(() => expect(workspaceApi.prepareFamilyTalk).toHaveBeenCalledWith(
    expect.objectContaining({ path_id: "path-1", person_id: "mother", evidence_ids: ["e1"] })));
  expect(await within(region).findByText("Start with the fees.")).toBeTruthy();
});

it("asks for education first, with a way to the Vault", async () => {
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue({ ...roadmapPage, education_line: null,
    fields: roadmapCards.map((c) => ({ ...c, status: "unknown", verdict: { ...c.verdict, status: "unknown", reasons: [{ key: "needs_education" }] } })) });
  const navigate = vi.fn();
  render(<Roadmap onNavigate={navigate} />);
  expect(await screen.findByText("Tell PAI your education first")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Go to Vault" }));
  expect(navigate).toHaveBeenCalledWith("profile");
});

it("says PAI is working out the fields when there are no paths yet", async () => {
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue({ ...roadmapPage, fields: [], counts: { open: 0, step: 0, not_open: 0, unknown: 0 } });
  render(<Roadmap onNavigate={vi.fn()} />);
  expect(await screen.findByText("PAI is working out your fields")).toBeTruthy();
});

it("tells a degree student that only undergraduate entry rules exist for now", async () => {
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue({ ...roadmapPage,
    education_line: { level: "bachelor", level_label: "Bachelor's", groups: [{ code: "computer_science", label: "Computer Science" }], percent: null },
    fields: roadmapCards.slice(0, 2).map((c) => ({ ...c, status: "unknown", verdict: { ...c.verdict, status: "unknown", reasons: [{ key: "undergrad_only" }] } })) });
  render(<Roadmap onNavigate={vi.fn()} />);
  expect(await screen.findByText("Undergraduate entry rules only for now.")).toBeTruthy();
  expect(screen.getByText("From Bachelor's Computer Science")).toBeTruthy();
});

it("has a template for every backend roadmap copy key, and renders groups as a route", () => {
  const policy = JSON.parse(readFileSync(resolve(__dirname, "../../../../backend/app/pai_c/policy/roadmap.json"), "utf8"));
  expect(Object.keys(copy.roadmap.templates).sort()).toEqual(Object.keys(policy.copy).sort());
  expect(copy.roadmap.templates).toEqual(policy.copy);
  expect(copy.roadmap.educationLine).toEqual(policy.education_line);
  expect(copy.roadmap.groupJoiner).toBe(policy.group_joiner);
  expect(copy.roadmap.officialConfidence).toBe(policy.official_confidence);
  expect(copy.roadmap.compareLimits).toEqual(policy.compare);
  expect(renderItem({ key: "step_group", groups: [{ code: "pre_engineering", label: "Pre-Engineering", route_label: "FSc Pre-Engineering" }] }))
    .toBe("Choose FSc Pre-Engineering in intermediate");
  expect(renderItem({ key: "choose_group", groups: [
    { code: "pre_engineering", label: "Pre-Engineering", route_label: "FSc Pre-Engineering" },
    { code: "ics", label: "ICS", route_label: "ICS" }] })).toBe("Choose FSc Pre-Engineering or ICS in intermediate");
});
