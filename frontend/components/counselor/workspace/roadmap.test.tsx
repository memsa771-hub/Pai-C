// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup, within } from "@testing-library/react";
import { Roadmap } from "./roadmap";
import { render as renderItem } from "./roadmap-text";
import { workspaceApi } from "@/lib/api";
import { chosenRoute, choiceOptionsOff, choiceOptionsOn, offeredPlaces, osPlanRoute, osRequestStep, roadmapCards, roadmapPage, routeChoice } from "@/tests/fixtures/counselor";
import { I18nProvider } from "@/lib/i18n";
import copy from "./copy.json";

vi.mock("next/navigation", async (original) => ({ ...(await original<typeof import("next/navigation")>()), useParams: () => ({ workspaceId: "ws1" }) }));
vi.mock("@/lib/api", () => ({
  workspaceApi: {
    getRoadmapPage: vi.fn(),
    chooseRoute: vi.fn(),
    choiceOptions: vi.fn(),
    places: vi.fn(),
    withdrawConsent: vi.fn(),
    giveConsent: vi.fn(),
    resendGuardian: vi.fn(),
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
  vi.mocked(workspaceApi.choiceOptions).mockResolvedValue(choiceOptionsOff);
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

it("opens a route sheet: every step with its colour, evidence, rule and time", async () => {
  render(<Roadmap onNavigate={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "See route for Electrical Engineering" }));
  const dialog = await screen.findByRole("dialog");
  const steps = [...within(dialog).getByRole("list", { name: "Electrical Engineering" }).querySelectorAll<HTMLElement>(":scope > li")];
  expect(steps.map((li) => li.querySelector("h3")?.textContent)).toEqual([
    "Choose FSc Pre-Engineering in intermediate", "Finish FSc (exam May 2027)", "Meet the 60% marks rule (you have 78%)",
    "Take ECAT / NET (pass 33%)", "Apply for Electrical Engineering", "Study Electrical Engineering (4 years)"]);
  // Colour is never alone: each step says its status in words.
  expect(steps.map((li) => li.getAttribute("data-status"))).toEqual(["done", "half", "done", "not", "not", "not"]);
  expect(steps.map((li) => li.querySelector("[data-status-word]")?.textContent)).toEqual(
    ["Done", "Partly done", "Done", "Not yet", "Not yet", "Not yet"]);
  // Evidence: the badge and where it came from; the rule behind the step links out.
  expect(within(steps[0]).getByText("From document")).toBeTruthy();
  expect(within(steps[0]).getByText("Result card.jpg")).toBeTruthy();
  const rule = within(steps[0]).getByRole("link", { name: /pec\.org\.pk/ });
  expect(rule.getAttribute("href")).toBe("https://www.pec.org.pk/regulations.pdf");
  expect(rule.getAttribute("rel")).toContain("noopener");
  expect(rule.className).toMatch(/\bmin-h-11\b/); // a 44px target, even when it looks small
  // When: the step's own month, then the entry and the total.
  expect(within(steps[1]).getByText("May 2027")).toBeTruthy();
  expect(within(steps[3]).getByText("June 2027")).toBeTruthy();
  expect(within(dialog).getByText("Entry: September intake, September 2027")).toBeTruthy();
  expect(within(dialog).getByText("About 11 months to entry · about 4.9 years to finish")).toBeTruthy();
  expect(within(dialog).getByText("Dates: Secondary source")).toBeTruthy();
  expect(within(dialog).getByText("Checked October 2026")).toBeTruthy();
  expect((within(dialog).getByRole("button", { name: "Choose this route" }) as HTMLButtonElement).disabled).toBe(false);
});

it("says the date is not confirmed when the calendar cannot place a step", async () => {
  render(<Roadmap onNavigate={vi.fn()} />);
  expect(within(await card("Pharmacy")).getByText("Date not confirmed")).toBeTruthy();
  expect(within(await card("Electrical Engineering")).getByText("About 11 months to entry")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "See route for Pharmacy" }));
  const dialog = await screen.findByRole("dialog");
  const test = within(dialog).getByRole("heading", { level: 3, name: "Take University test" }).closest("li")!;
  expect(within(test).getByText("Date not confirmed")).toBeTruthy();
  expect(within(dialog).getByText("Dates not confirmed; check the official schedule")).toBeTruthy();
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
  const cells = (name: string) => [...within(table).getByRole("rowheader", { name }).parentElement!.querySelectorAll("td")].map((td) => td.textContent);
  expect(cells("Steps done")).toEqual(["2 of 6", "2 of 6", "2 of 7"]);
  expect(cells("Time to entry")).toEqual(["About 11 months", "About 10 months · Not confirmed", "Not confirmed"]);
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

const ticked = (key: string, done: boolean) => ({ ...chosenRoute, steps_done: done ? [key] : [],
  steps: chosenRoute.steps.map((s) => (s.key === key ? { ...s, status: done ? "done" as const : "not" as const, manual_done: done } : s)) });

it("tells the shell after choose, tick and withdraw so the journey stage refreshes", async () => {
  const changed = vi.fn();
  vi.mocked(workspaceApi.chooseRoute).mockResolvedValue(chosenRoute);
  render(<Roadmap onNavigate={vi.fn()} onChanged={changed} />);
  fireEvent.click(await screen.findByRole("button", { name: "See route for Electrical Engineering" }));
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue({ ...roadmapPage, chosen: chosenRoute });
  fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Choose this route" }));
  await waitFor(() => expect(changed).toHaveBeenCalledTimes(1));
  vi.mocked(workspaceApi.setRouteStep).mockResolvedValueOnce(ticked("apply", true));
  fireEvent.click(await screen.findByRole("checkbox", { name: "Apply for Electrical Engineering" }));
  await waitFor(() => expect(changed).toHaveBeenCalledTimes(2));
  vi.mocked(workspaceApi.withdrawRoute).mockResolvedValue(chosenRoute);
  fireEvent.click(screen.getByRole("button", { name: "Change route" }));
  fireEvent.click(screen.getByRole("button", { name: "Yes, change route" }));
  await waitFor(() => expect(changed).toHaveBeenCalledTimes(3));
});

it("chooses a route and shows it at the top: coloured steps, progress by status and the time", async () => {
  vi.mocked(workspaceApi.chooseRoute).mockResolvedValue(chosenRoute);
  render(<Roadmap onNavigate={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "See route for Electrical Engineering" }));
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue({ ...roadmapPage, chosen: chosenRoute });
  fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Choose this route" }));
  await waitFor(() => expect(workspaceApi.chooseRoute).toHaveBeenCalledWith("electrical_engineering"));
  const route = await screen.findByRole("region", { name: "Your route" });
  expect(within(route).getByText("Electrical Engineering")).toBeTruthy();
  // Done steps are the green ones, whatever made them green.
  expect(within(route).getByText("2 of 6")).toBeTruthy();
  expect(within(route).getByText("About 11 months to entry · about 4.9 years to finish")).toBeTruthy();
  const items = [...within(route).getByRole("list", { name: "Your steps" }).querySelectorAll(":scope > li")];
  expect(items.map((li) => li.getAttribute("data-status"))).toEqual(["done", "half", "done", "not", "not", "not"]);
  // A manual tick only where the student can claim it: the test (not yet) and applying.
  expect(within(route).getAllByRole("checkbox").map((box) => box.getAttribute("aria-label") || (box.closest("label")?.textContent ?? "")))
    .toEqual(["Take ECAT / NET (pass 33%)", "Apply for Electrical Engineering"]);
});

it("offers a tick only where the backend says the Vault is silent", async () => {
  // Marks below the floor are red but read from the record: no tick, whatever the colour.
  const steps = chosenRoute.steps.map((s) => (s.key === "marks" ? { ...s, status: "not" as const, values: { min: 60, have: 55 } } : s));
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue({ ...roadmapPage, chosen: { ...chosenRoute, steps } });
  render(<Roadmap onNavigate={vi.fn()} />);
  const route = await screen.findByRole("region", { name: "Your route" });
  expect(within(route).queryByRole("checkbox", { name: "Meet the 60% marks rule (you have 55%)" })).toBeNull();
  expect(within(route).queryByRole("checkbox", { name: "Study Electrical Engineering (4 years)" })).toBeNull();
  expect(within(route).getAllByRole("checkbox")).toHaveLength(2);
});

it("ticks a step by its key through the API and reverts when it fails", async () => {
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue({ ...roadmapPage, chosen: chosenRoute });
  vi.mocked(workspaceApi.setRouteStep).mockResolvedValueOnce(ticked("test:ECAT / NET", true));
  render(<Roadmap onNavigate={vi.fn()} />);
  const box = (await screen.findByRole("checkbox", { name: "Take ECAT / NET (pass 33%)" })) as HTMLInputElement;
  fireEvent.click(box);
  expect(box.checked).toBe(true); // optimistic
  await waitFor(() => expect(workspaceApi.setRouteStep).toHaveBeenCalledWith("test:ECAT / NET", true));
  expect(await screen.findByText("3 of 6")).toBeTruthy();
  // A ticked step without Vault proof reads "You marked it", at the stated level.
  const test = screen.getByRole("checkbox", { name: "Take ECAT / NET (pass 33%)" }).closest("li")!;
  expect(test.getAttribute("data-status")).toBe("done");
  vi.mocked(workspaceApi.setRouteStep).mockRejectedValueOnce(new Error("offline"));
  const apply = screen.getByRole("checkbox", { name: "Apply for Electrical Engineering" }) as HTMLInputElement;
  fireEvent.click(apply);
  await waitFor(() => expect(apply.checked).toBe(false));
  expect(screen.getByRole("alert").textContent).toBe(copy.roadmap.error);
});

it("blocks a second tick while a save is in flight, and a failure reverts only its own step", async () => {
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue({ ...roadmapPage, chosen: ticked("apply", true) });
  let fail!: (error: Error) => void;
  vi.mocked(workspaceApi.setRouteStep).mockReturnValueOnce(new Promise((_, reject) => { fail = reject; }));
  render(<Roadmap onNavigate={vi.fn()} />);
  const apply = (await screen.findByRole("checkbox", { name: "Apply for Electrical Engineering" })) as HTMLInputElement;
  const test = screen.getByRole("checkbox", { name: "Take ECAT / NET (pass 33%)" }) as HTMLInputElement;
  expect(apply.checked).toBe(true);
  fireEvent.click(test);
  expect(test.checked).toBe(true);
  fireEvent.click(test); // a double click while saving
  fireEvent.click(apply);
  expect(workspaceApi.setRouteStep).toHaveBeenCalledTimes(1);
  fail(new Error("offline"));
  await waitFor(() => expect(test.checked).toBe(false));
  expect(apply.checked).toBe(true); // the other ticks stay as they were
  expect(screen.getByRole("alert").textContent).toBe(copy.roadmap.error);
});

it("changes route only after a confirm, and notes a changed situation", async () => {
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue({ ...roadmapPage, chosen: { ...chosenRoute, live_status: "step" } });
  vi.mocked(workspaceApi.withdrawRoute).mockResolvedValue(chosenRoute);
  render(<Roadmap onNavigate={vi.fn()} />);
  expect(await screen.findByText("Your situation changed: now a step away.")).toBeTruthy();
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
  // Every step status the engine colours has its word.
  for (const status of Object.keys(policy.steps.colours)) expect(copy.roadmap.templates).toHaveProperty([`status_${status}`]);
  expect(renderItem({ key: "step_group", groups: [{ code: "pre_engineering", label: "Pre-Engineering", route_label: "FSc Pre-Engineering" }] }))
    .toBe("Choose FSc Pre-Engineering in intermediate");
  expect(renderItem({ key: "choose_group", groups: [
    { code: "pre_engineering", label: "Pre-Engineering", route_label: "FSc Pre-Engineering" },
    { code: "ics", label: "ICS", route_label: "ICS" }] })).toBe("Choose FSc Pre-Engineering or ICS in intermediate");
});

it("fits a 375px phone: the route list and the sheet wrap instead of overflowing", async () => {
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue({ ...roadmapPage, chosen: chosenRoute });
  const { baseElement } = render(<Roadmap onNavigate={vi.fn()} />);
  await screen.findByRole("region", { name: "Your route" });
  fireEvent.click(screen.getByRole("button", { name: "See route for Electrical Engineering" }));
  await screen.findByRole("dialog");
  for (const li of baseElement.querySelectorAll("li[data-status]")) expect(li.className).toMatch(/\bmin-w-0\b/);
  const widths = [...baseElement.querySelectorAll("[class]")].flatMap((el) =>
    [...String(el.getAttribute("class")).matchAll(/\b(?:min-)?w-\[(\d+)px\]/g)].map((m) => +m[1]));
  expect(widths.every((w) => w <= 343)).toBe(true);
});

// req: R-79
it("with the hand-off off, Choose is one click: no choice screens, chooseRoute with the field key only", async () => {
  vi.mocked(workspaceApi.chooseRoute).mockResolvedValue(chosenRoute);
  render(<Roadmap onNavigate={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "See route for Electrical Engineering" }));
  fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Choose this route" }));
  await waitFor(() => expect(workspaceApi.chooseRoute).toHaveBeenCalledTimes(1));
  expect(vi.mocked(workspaceApi.chooseRoute).mock.calls[0]).toEqual(["electrical_engineering"]);
  expect(workspaceApi.choiceOptions).toHaveBeenCalledWith("electrical_engineering");
  expect(screen.queryByTestId("choice-step")).toBeNull();
});

// req: R-79
it("with the hand-off on, Choose opens the choice screens and saves nothing yet", async () => {
  vi.mocked(workspaceApi.choiceOptions).mockResolvedValue(choiceOptionsOn);
  vi.mocked(workspaceApi.places).mockResolvedValue({ handoff: true, places: offeredPlaces });
  vi.mocked(workspaceApi.chooseRoute).mockResolvedValue({ ...chosenRoute, choice: routeChoice() });
  const changed = vi.fn();
  render(<I18nProvider><Roadmap onNavigate={vi.fn()} onChanged={changed} /></I18nProvider>);
  fireEvent.click(await screen.findByRole("button", { name: "See route for Electrical Engineering" }));
  fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Choose this route" }));
  expect((await screen.findByTestId("choice-step")).textContent).toBe("Step 1 of 4: Country");
  expect(workspaceApi.chooseRoute).not.toHaveBeenCalled();
  // Through to the end: the page reloads and the shell is told.
  const c = copy.roadmap.choice;
  fireEvent.click(screen.getAllByRole("radio")[1]);
  fireEvent.click(screen.getByRole("button", { name: c.next }));
  fireEvent.change(screen.getByLabelText(c.intake.term), { target: { value: "winter" } });
  fireEvent.change(screen.getByLabelText(c.intake.year), { target: { value: "2027" } });
  fireEvent.click(screen.getByRole("button", { name: c.next }));
  fireEvent.click(await screen.findByRole("checkbox", { name: "Alpha University" }));
  fireEvent.click(screen.getByRole("button", { name: c.next }));
  fireEvent.click(screen.getByRole("checkbox", { name: c.consent.agree }));
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue({ ...roadmapPage, chosen: { ...chosenRoute, choice: routeChoice() } });
  fireEvent.click(screen.getByRole("button", { name: c.submit }));
  await waitFor(() => expect(changed).toHaveBeenCalledTimes(1));
  expect(await screen.findByRole("region", { name: "Your route" })).toBeTruthy();
});

const cs = copy.roadmap.choice.consentState;
const chosenWith = (choice: ReturnType<typeof routeChoice>) => ({ ...roadmapPage, chosen: { ...chosenRoute, choice } });

// req: R-10
it("shows who has agreed on the chosen route, in words", async () => {
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue(chosenWith(routeChoice({ consent: { student: "given", guardian: "missing" } })));
  render(<Roadmap onNavigate={vi.fn()} />);
  const panel = await screen.findByRole("region", { name: cs.title });
  expect(within(panel).getByText(cs.studentGiven)).toBeTruthy();
  expect(within(panel).getByText(cs.guardianMissing)).toBeTruthy();
  expect(within(panel).getByText(cs.waiting)).toBeTruthy();
});

// req: R-10
it("shows no consent block when the hand-off is off (no choice on the route)", async () => {
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue({ ...roadmapPage, chosen: chosenRoute });
  render(<Roadmap onNavigate={vi.fn()} />);
  await screen.findByRole("region", { name: "Your route" });
  expect(screen.queryByRole("region", { name: cs.title })).toBeNull();
});

// req: R-10
it("withdraws consent behind one confirm, then gives it again and asks for the guardian link to be resent", async () => {
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue(chosenWith(routeChoice({ consent: { student: "given", guardian: "missing" } })));
  render(<Roadmap onNavigate={vi.fn()} />);
  const panel = await screen.findByRole("region", { name: cs.title });
  fireEvent.click(within(panel).getByRole("button", { name: cs.withdraw }));
  expect(workspaceApi.withdrawConsent).not.toHaveBeenCalled(); // asks first
  vi.mocked(workspaceApi.withdrawConsent).mockResolvedValue({ choice: routeChoice({ consent: { student: "missing", guardian: "missing" },
    consent_version: null, consent_offer: { text: choiceOptionsOn.consent_text, version: "1" } }) });
  fireEvent.click(within(panel).getByRole("button", { name: cs.withdrawYes }));
  expect(await within(panel).findByText(cs.studentMissing)).toBeTruthy();
  expect(within(panel).getByText(cs.pausedNote)).toBeTruthy();
  // Give it again: the text is shown first and its version is sent (I2). The old guardian link no longer counts,
  // so the student is then asked to send a new one.
  vi.mocked(workspaceApi.giveConsent).mockResolvedValue({ choice: routeChoice({ consent: { student: "given", guardian: "missing" } }) });
  fireEvent.click(within(panel).getByRole("button", { name: cs.give }));
  expect(workspaceApi.giveConsent).not.toHaveBeenCalled();
  expect(within(panel).getByText(choiceOptionsOn.consent_text!.title)).toBeTruthy();
  fireEvent.click(within(panel).getByRole("button", { name: cs.giveYes }));
  await waitFor(() => expect(workspaceApi.giveConsent).toHaveBeenCalledWith("1"));
  expect(await within(panel).findByText(cs.resendPrompt)).toBeTruthy();
  // The address is asked again: it is not kept for a resend.
  vi.mocked(workspaceApi.resendGuardian).mockResolvedValue({ sent: true });
  fireEvent.click(within(panel).getByRole("button", { name: cs.resendSend }));
  expect(within(panel).getByRole("alert").textContent).toContain(cs.resendRequired);
  expect(workspaceApi.resendGuardian).not.toHaveBeenCalled();
  fireEvent.change(within(panel).getByLabelText(cs.resendLabel), { target: { value: "parent@example.com" } });
  fireEvent.click(within(panel).getByRole("button", { name: cs.resendSend }));
  await waitFor(() => expect(workspaceApi.resendGuardian).toHaveBeenCalledWith("parent@example.com"));
  expect(await within(panel).findByText(cs.resendSent)).toBeTruthy();
});

// req: R-10
it("keeps consent as it was and says so when withdrawing fails", async () => {
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue(chosenWith(routeChoice()));
  vi.mocked(workspaceApi.withdrawConsent).mockRejectedValue(new Error("API 500: x"));
  render(<Roadmap onNavigate={vi.fn()} />);
  const panel = await screen.findByRole("region", { name: cs.title });
  fireEvent.click(within(panel).getByRole("button", { name: cs.withdraw }));
  fireEvent.click(within(panel).getByRole("button", { name: cs.withdrawYes }));
  expect((await within(panel).findByRole("alert")).textContent).toContain(cs.error);
  expect(within(panel).getByText(cs.studentGiven)).toBeTruthy();
});

// req: R-79
it("chooses nothing and shows an error when the choice options cannot be read", async () => {
  // Rule change (final review I4): this test used to assert a one-click fallback on failure. A choose without
  // details could close a plan PAI OS runs, so only an answer of `handoff: false` allows the one-click choose.
  vi.mocked(workspaceApi.choiceOptions).mockRejectedValue(new Error("API 500: x"));
  vi.mocked(workspaceApi.chooseRoute).mockResolvedValue(chosenRoute);
  render(<Roadmap onNavigate={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "See route for Electrical Engineering" }));
  const sheet = await screen.findByRole("dialog");
  fireEvent.click(within(sheet).getByRole("button", { name: "Choose this route" }));
  expect((await within(sheet).findByRole("alert")).textContent).toContain(copy.roadmap.error);
  expect(workspaceApi.chooseRoute).not.toHaveBeenCalled();
  expect(screen.queryByTestId("choice-step")).toBeNull();
});

// req: R-10
it("shows the text before giving consent and says so when it is not approved", async () => {
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue(chosenWith(routeChoice({
    consent: { student: "missing", guardian: "not_needed" }, consent_offer: { text: null, version: "1" } })));
  render(<Roadmap onNavigate={vi.fn()} />);
  const panel = await screen.findByRole("region", { name: cs.title });
  fireEvent.click(within(panel).getByRole("button", { name: cs.give }));
  expect(within(panel).getByRole("alert").textContent).toContain(cs.textNotReady);
  expect(within(panel).queryByRole("button", { name: cs.giveYes })).toBeNull();
  expect(workspaceApi.giveConsent).not.toHaveBeenCalled();
});

// req: R-10
it("sends the guardian a new withdraw link once they have agreed", async () => {
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue(chosenWith(routeChoice({ consent: { student: "given", guardian: "given" } })));
  vi.mocked(workspaceApi.resendGuardian).mockResolvedValue({ sent: true, kind: "withdraw" });
  render(<Roadmap onNavigate={vi.fn()} />);
  const panel = await screen.findByRole("region", { name: cs.title });
  fireEvent.click(within(panel).getByRole("button", { name: cs.withdrawLink }));
  await waitFor(() => expect(workspaceApi.resendGuardian).toHaveBeenCalledWith());
  expect(await within(panel).findByText(cs.withdrawLinkSent)).toBeTruthy();
});

// req: R-44, R-04 (the OS plan on the roadmap screen)
const osPage = (over: Partial<typeof osPlanRoute> = {}) => ({ ...roadmapPage, chosen: { ...osPlanRoute, ...over } });

it("shows OS plan steps by title with owner, due date and the plan state banner", async () => {
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue(osPage());
  render(<Roadmap onNavigate={vi.fn()} />);
  expect(await screen.findByText("Collect your transcripts")).toBeTruthy();
  expect(screen.getByText("Draft the statement of purpose")).toBeTruthy();
  expect(screen.getByText("Due March 12, 2027")).toBeTruthy();
  expect(screen.getByText(copy.roadmap.plan.needs_student)).toBeTruthy();
  expect(screen.getAllByText(copy.roadmap.plan.owner_pai).length).toBe(2);
  expect(screen.queryByText(copy.roadmap.route.unsupported)).toBeNull();
});

it.each(["empty", "paused", "stopped", "finished"] as const)("shows the %s plan banner", async (state) => {
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue(osPage({ plan: { state } }));
  render(<Roadmap onNavigate={vi.fn()} />);
  expect(await screen.findByText(copy.roadmap.plan[state])).toBeTruthy();
});

it("shows no plan banner for an active plan", async () => {
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue(osPage({ plan: { state: "active" } }));
  render(<Roadmap onNavigate={vi.fn()} />);
  await screen.findByText("Collect your transcripts");
  expect(document.querySelector("[data-plan-state]")).toBeNull();
});

it("ticks an OS step through setRouteStep and then offers no untick", async () => {
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue(osPage());
  const route = osPage().chosen;
  vi.mocked(workspaceApi.setRouteStep).mockResolvedValueOnce({ ...route, steps: route.steps.map((s) => s.key === "collect-transcripts"
    ? { ...s, status: "done", tickable: false } : s) });
  render(<Roadmap onNavigate={vi.fn()} />);
  fireEvent.click(await screen.findByRole("checkbox", { name: "Collect your transcripts" }));
  await waitFor(() => expect(workspaceApi.setRouteStep).toHaveBeenCalledWith("collect-transcripts", true));
  await waitFor(() => expect(screen.queryByRole("checkbox", { name: "Collect your transcripts" })).toBeNull());
  expect(screen.queryByRole("checkbox", { name: /transcripts|deadline|statement/ })).toBeNull();
});

it("never offers a tick on a PAI-owned or done OS step", async () => {
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue(osPage());
  render(<Roadmap onNavigate={vi.fn()} />);
  await screen.findByText("Collect your transcripts");
  expect(screen.queryByRole("checkbox", { name: "Check the application deadline" })).toBeNull();
  expect(screen.queryByRole("checkbox", { name: "Draft the statement of purpose" })).toBeNull();
});

it("says PAI can't run the plan yet only when the choice is not OS supported", async () => {
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue(chosenWith(routeChoice({ os_supported: false })));
  render(<Roadmap onNavigate={vi.fn()} />);
  expect(await screen.findByText(copy.roadmap.route.unsupported)).toBeTruthy();
  cleanup();
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue(chosenWith(routeChoice({ os_supported: true })));
  render(<Roadmap onNavigate={vi.fn()} />);
  await screen.findByRole("checkbox", { name: "Take ECAT / NET (pass 33%)" });
  expect(screen.queryByText(copy.roadmap.route.unsupported)).toBeNull();
});

it("renders a flag-off route (no plan, no OS steps) with no plan banner or owner", async () => {
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue({ ...roadmapPage, chosen: chosenRoute });
  render(<Roadmap onNavigate={vi.fn()} />);
  await screen.findByRole("checkbox", { name: "Take ECAT / NET (pass 33%)" });
  expect(document.querySelector("[data-plan-state],[data-owner],[data-unsupported]")).toBeNull();
});

// req: R-44, R-04 (fix round 1)
it("words a paused plan by its reason when copy.json has one, else neutrally", async () => {
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue(osPage({ plan: { state: "paused", state_reason: "consent_missing" } }));
  render(<Roadmap onNavigate={vi.fn()} />);
  expect(await screen.findByText(copy.roadmap.plan.paused_consent_missing)).toBeTruthy();
  cleanup();
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue(osPage({ plan: { state: "paused", state_reason: "some_new_reason" } }));
  render(<Roadmap onNavigate={vi.fn()} />);
  expect(await screen.findByText(copy.roadmap.plan.paused)).toBeTruthy();
  cleanup();
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue(osPage({ plan: { state: "stopped", state_reason: "route_changed" } }));
  render(<Roadmap onNavigate={vi.fn()} />);
  expect(await screen.findByText(copy.roadmap.plan.stopped)).toBeTruthy();
});

it("never renders a tick for a PAI-owned step even when tickable is true", async () => {
  const route = osPage().chosen;
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue(osPage({ steps: route.steps.map((s) =>
    s.key === "draft-statement" ? { ...s, tickable: true, owner: "pai" as const } : s) }));
  render(<Roadmap onNavigate={vi.fn()} />);
  await screen.findByText("Draft the statement of purpose");
  expect(screen.queryByRole("checkbox", { name: "Draft the statement of purpose" })).toBeNull();
});

it("keeps an OS step's checkbox (disabled) while it saves, and reverts with the alert when the save fails", async () => {
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue(osPage());
  let fail!: (error: Error) => void;
  vi.mocked(workspaceApi.setRouteStep).mockReturnValueOnce(new Promise((_, reject) => { fail = reject; }));
  render(<Roadmap onNavigate={vi.fn()} />);
  fireEvent.click(await screen.findByRole("checkbox", { name: "Collect your transcripts" }));
  const box = screen.getByRole("checkbox", { name: "Collect your transcripts" }) as HTMLInputElement;
  expect(box.disabled).toBe(true);
  fail(new Error("503"));
  expect(await screen.findByRole("alert")).toBeTruthy();
  const back = screen.getByRole("checkbox", { name: "Collect your transcripts" }) as HTMLInputElement;
  expect(back.checked).toBe(false);
  expect(back.disabled).toBe(false);
  expect(screen.getByText("Collect your transcripts").closest("li")!.getAttribute("data-status")).toBe("half");
});

// req: R-11
it("PlanBanner shows reason_text and one action that opens change route", async () => {
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue(osPage({ plan: { state: "paused", state_reason: "all_rejected",
    reason_text: "None of your places took you.", reason_action: "Choose again" } }));
  render(<Roadmap onNavigate={vi.fn()} />);
  expect(await screen.findByText("None of your places took you.")).toBeTruthy();
  expect(screen.queryByText(copy.roadmap.plan.paused)).toBeNull();
  const banner = document.querySelector("[data-plan-state]") as HTMLElement;
  const buttons = within(banner).getAllByRole("button");
  expect(buttons.length).toBe(1);
  fireEvent.click(buttons[0]);
  const yes = await screen.findByRole("button", { name: copy.roadmap.route.changeYes });
  await waitFor(() => expect(document.activeElement).toBe(yes.parentElement?.parentElement));  // focus moves to the confirm
});

// req: R-11
it("PlanBanner shows reason_text with no button when there is no reason_action, and nothing new when both are null", async () => {
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue(osPage({ plan: { state: "paused", reason_text: "None of your places took you." } }));
  render(<Roadmap onNavigate={vi.fn()} />);
  expect(await screen.findByText("None of your places took you.")).toBeTruthy();
  expect(within(document.querySelector("[data-plan-state]") as HTMLElement).queryByRole("button")).toBeNull();
  cleanup();
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue(osPage({ plan: { state: "paused", reason_text: null, reason_action: null } }));
  render(<Roadmap onNavigate={vi.fn()} />);
  expect(await screen.findByText(copy.roadmap.plan.paused)).toBeTruthy();
  expect(within(document.querySelector("[data-plan-state]") as HTMLElement).queryByRole("button")).toBeNull();
});

// req: R-54
it("with My plan on, a dated OS step shows its level and links to the inbox; a firm date shows no level", async () => {
  const { MyPlanContext } = await import("@/components/os/my-plan-context");
  const steps = osPlanRoute.steps.map((s) => s.key === "collect-transcripts" ? { ...s, estimated: true } : s);
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue(osPage({ steps }));
  const plan = { state: "active", source: null, plan_id: 1, route_key: "r", abroad: true, pages: [], sources: {} };
  render(<MyPlanContext.Provider value={{ on: true, plan, refresh: () => {} }}><Roadmap onNavigate={vi.fn()} /></MyPlanContext.Provider>);
  await screen.findByText("Collect your transcripts");
  expect(screen.getAllByText(copy.connect.myPlan.levels.estimated).length).toBe(1);
  expect(screen.queryByText(copy.connect.myPlan.levels.not_confirmed)).toBeNull();
  const link = screen.getByRole("link", { name: copy.connect.myPlan.dateSource });
  expect(link.getAttribute("href")).toBe("/ws1/os-inbox");
  cleanup();
  render(<Roadmap onNavigate={vi.fn()} />);
  await screen.findByText("Collect your transcripts");
  expect(screen.queryByText(copy.connect.myPlan.levels.estimated)).toBeNull();
  expect(screen.queryByRole("link", { name: copy.connect.myPlan.dateSource })).toBeNull();
});

// req: R-19 (P1-T8 Task 6: a step that waits for the student's data shows its request line and no tick)
it("roadmap shows the request line and no tick", async () => {
  const steps = [...osPlanRoute.steps, osRequestStep];
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue(osPage({ steps }));
  render(<Roadmap onNavigate={vi.fn()} />);
  expect(await screen.findByText(osRequestStep.request!.text)).toBeTruthy();
  expect(screen.getByRole("checkbox", { name: "Collect your transcripts" })).toBeTruthy();  // an ordinary student step keeps its tick
  expect(screen.queryByRole("checkbox", { name: "Your matric marks" })).toBeNull();
  expect(document.querySelectorAll("[data-request]").length).toBe(1);
});

it("a plan with no request step shows no request line", async () => {
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue(osPage());
  render(<Roadmap onNavigate={vi.fn()} />);
  await screen.findByText("Collect your transcripts");
  expect(document.querySelector("[data-request]")).toBeNull();
});
