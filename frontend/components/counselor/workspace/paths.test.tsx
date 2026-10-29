// @vitest-environment jsdom
import { it, expect, vi, afterEach, beforeEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  cleanup,
  act,
} from "@testing-library/react";
import { Paths, PathPage, ProgramPage } from "./paths";
import { workspaceApi } from "@/lib/api";
import {
  possibilities,
  pathResult,
  programs,
} from "@/tests/fixtures/counselor";
vi.mock("@/lib/api", () => ({
  workspaceApi: {
    getPossibilities: vi.fn(),
    changePossibility: vi.fn(),
    getPath: vi.fn(),
    getPrograms: vi.fn(),
    searchPrograms: vi.fn(),
    addOwnPath: vi.fn(),
    getPathAnalysis: vi.fn(),
  },
}));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
beforeEach(() => {
  vi.mocked(workspaceApi.getPathAnalysis).mockResolvedValue({ job_id: null, done: true, outcome: null });
});
it("opens a path without initiating program research", async () => {
  vi.mocked(workspaceApi.getPossibilities).mockResolvedValue(possibilities);
  const open = vi.fn();
  render(<Paths onOpen={open} />);
  fireEvent.click((await screen.findAllByText("Explore"))[0]);
  expect(open).toHaveBeenCalledWith("path-one");
  expect(workspaceApi.searchPrograms).not.toHaveBeenCalled();
});
it("lists paths with a fit summary and shows each verdict with the student's words on the path page", async () => {
  vi.mocked(workspaceApi.getPossibilities).mockResolvedValue(possibilities);
  render(<Paths onOpen={vi.fn()} />);
  const row = (await screen.findByText("Practical design")).closest("li")!;
  expect(row.querySelector('[role="img"]')?.getAttribute("aria-label"))
    .toBe("1 you have, 1 partly, 0 in the way, 1 not known yet");
  vi.mocked(workspaceApi.getPath).mockResolvedValue(pathResult);
  cleanup();
  render(<PathPage id="path-one" onBack={vi.fn()} onPlaces={vi.fn()} onChat={vi.fn()} />);
  expect(await screen.findByText("How it fits you")).toBeTruthy();
  expect(screen.getByText("You already repair and build things.")).toBeTruthy();
  expect(screen.getByText("From what you said: “I sketch before I build.”")).toBeTruthy();
});
it("adds the student's own path and follows PAI's run, with no find button", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.mocked(workspaceApi.getPossibilities).mockResolvedValue(possibilities);
  vi.mocked(workspaceApi.addOwnPath).mockResolvedValue({ ...possibilities[1], id: "mine", title: "Nursing" });
  render(<Paths onOpen={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Add your own path" }));
  expect(screen.queryByRole("button", { name: "Find my paths" })).toBeNull();
  const add = screen.getByRole("button", { name: "Add path" }) as HTMLButtonElement;
  expect(add.disabled).toBe(true);
  fireEvent.change(screen.getByLabelText("Path"), { target: { value: "  Nursing " } });
  fireEvent.change(screen.getByLabelText("Why it interests you (optional)"), { target: { value: "I like caring" } });
  vi.mocked(workspaceApi.getPathAnalysis).mockResolvedValue({ job_id: "job", done: false, outcome: null });
  fireEvent.click(add);
  await waitFor(() => expect(workspaceApi.addOwnPath).toHaveBeenCalledWith("Nursing", "I like caring"));
  expect(await screen.findByText(/PAI is looking at everything/)).toBeTruthy();
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(vi.mocked(workspaceApi.getPossibilities).mock.calls.length).toBeGreaterThan(2);
  vi.mocked(workspaceApi.getPathAnalysis).mockResolvedValue({ job_id: "job", done: true, outcome: "saved" });
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  await waitFor(() => expect(screen.queryByText(/PAI is looking at everything/)).toBeNull());
  vi.useRealTimers();
});
it("shows general explanation and invites deeper research only afterwards", async () => {
  vi.mocked(workspaceApi.getPath).mockResolvedValue(pathResult);
  const places = vi.fn();
  render(
    <PathPage
      id="path-one"
      onBack={vi.fn()}
      onPlaces={places}
      onChat={vi.fn()}
    />,
  );
  expect(await screen.findByText("What you study")).toBeTruthy();
  fireEvent.click(
    screen.getByRole("button", { name: "Look at places" }),
  );
  expect(places).toHaveBeenCalledOnce();
  expect(workspaceApi.searchPrograms).not.toHaveBeenCalled();
});
it("H requires explicit consent, preserves no-source state", async () => {
  vi.mocked(workspaceApi.getPrograms)
    .mockResolvedValueOnce({ status: "not_started", programs: [], missing: [] })
    .mockResolvedValue(programs);
  render(<ProgramPage id="path-one" onBack={vi.fn()} />);
  const button = await screen.findByRole("button", {
    name: "Look at programs",
  });
  expect((button as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(button);
  await waitFor(() =>
    expect(workspaceApi.searchPrograms).toHaveBeenCalledExactlyOnceWith(
      "path-one",
    ),
  );
  expect(
    await screen.findByText(/No verified program information/),
  ).toBeTruthy();
});

it('expired evidence requires fresh consent and offers no next step',async()=>{
 vi.mocked(workspaceApi.getPrograms).mockResolvedValue({status:'stale',programs:[],missing:['expired_sources']});
 render(<ProgramPage id='path-one' onBack={vi.fn()}/>);
 const button=await screen.findByRole('button',{name:'Look at programs'});
 expect((button as HTMLButtonElement).disabled).toBe(true);
 expect(screen.queryByRole('button',{name:'Open Roadmap'})).toBeNull();
 expect(workspaceApi.searchPrograms).not.toHaveBeenCalled();
});

it('a completed places search points to the Roadmap page without starting work',async()=>{
 vi.mocked(workspaceApi.getPrograms).mockResolvedValue({...programs,status:'completed'});
 const onRoadmap=vi.fn();
 render(<ProgramPage id='path-one' onBack={vi.fn()} onRoadmap={onRoadmap}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Open Roadmap'}));
 expect(onRoadmap).toHaveBeenCalledOnce();
 expect(workspaceApi.searchPrograms).not.toHaveBeenCalled();
});

it('polls durable pending jobs until a result exists',async()=>{
 vi.useFakeTimers();
 try {
  vi.mocked(workspaceApi.getPath).mockResolvedValue({...pathResult,status:'pending',path:null});
  await act(async()=>{render(<PathPage id='path-one' onBack={vi.fn()} onPlaces={vi.fn()} onChat={vi.fn()}/>);});
  expect(workspaceApi.getPath).toHaveBeenCalledTimes(1);
  await act(async()=>{await vi.advanceTimersByTimeAsync(5000);});
  expect(workspaceApi.getPath).toHaveBeenCalledTimes(2);
 } finally {cleanup();vi.useRealTimers();}
});

it("shows a study field's group notes on the path row and the path page, never raw codes", async () => {
  const field = { ...possibilities[0], title: "Electrical Engineering",
    study_field: { key: "electrical_engineering", needs_check: true, needs_group: [{ code: "pre_engineering", label: "Pre-Engineering" }] } };
  const older = { ...possibilities[1], id: "older", title: "Mechanics and metal trades", status: "saved" as const, study_field: { outdated: true } };
  vi.mocked(workspaceApi.getPossibilities).mockResolvedValue([field, older]);
  render(<Paths onOpen={vi.fn()} />);
  const row = (await screen.findByText("Electrical Engineering")).closest("li")!;
  expect(row.textContent).toContain("Needs checking for your group");
  expect(row.textContent).toContain("Needs Pre-Engineering in intermediate");
  expect(row.textContent).not.toContain("pre_engineering");
  expect(screen.getByText("Mechanics and metal trades").closest("li")!.textContent).toContain("Older suggestion");
  cleanup();
  vi.mocked(workspaceApi.getPath).mockResolvedValue({ ...pathResult, possibility: field });
  render(<PathPage id="path-one" onBack={vi.fn()} onPlaces={vi.fn()} onChat={vi.fn()} />);
  expect(await screen.findByText("Needs checking for your group")).toBeTruthy();
});

it("marks a kept field outside the current group and lets the student remove an older suggestion", async () => {
  const kept = { ...possibilities[0], title: "Pharm-D", status: "saved" as const,
    study_field: { key: "pharm_d", needs_check: false, needs_group: [], out_of_group: true } };
  const older = { ...possibilities[1], id: "older", title: "Computer use", status: "saved" as const, study_field: { outdated: true } };
  vi.mocked(workspaceApi.getPossibilities).mockResolvedValue([kept, older]);
  vi.mocked(workspaceApi.changePossibility).mockResolvedValue({ ...older, status: "dismissed" });
  render(<Paths onOpen={vi.fn()} />);
  expect((await screen.findByText("Pharm-D")).closest("li")!.textContent).toContain("Not open to your current group");
  const row = screen.getByText("Computer use").closest("li")!;
  expect(row.textContent).toContain("Older suggestion, from before fields of study");
  fireEvent.click(screen.getByRole("button", { name: "Remove" }));
  await waitFor(() => expect(workspaceApi.changePossibility).toHaveBeenCalledWith("older", "dismiss"));
});

it("asks for the education when the last run needed it, and shows PAI's own run until it ends", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  try {
    vi.mocked(workspaceApi.getPossibilities).mockResolvedValue(possibilities);
    vi.mocked(workspaceApi.getPathAnalysis).mockResolvedValue({ job_id: "job-1", done: true, outcome: "needs_education" });
    render(<Paths onOpen={vi.fn()} />);
    expect(await screen.findByText("PAI needs your group or field to suggest fields of study.")).toBeTruthy();
    cleanup();
    // A run PAI started on its own (e.g. after an education write) shows while it works.
    vi.mocked(workspaceApi.getPathAnalysis).mockResolvedValue({ job_id: "job-2", done: false, outcome: null });
    render(<Paths onOpen={vi.fn()} />);
    expect(await screen.findByText(/PAI is looking at everything/)).toBeTruthy();
    vi.mocked(workspaceApi.getPathAnalysis).mockResolvedValue({ job_id: "job-2", done: true, outcome: "needs_education" });
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    await waitFor(() => expect(screen.getByText("PAI needs your group or field to suggest fields of study.")).toBeTruthy());
    expect(screen.queryByText(/PAI is looking at everything/)).toBeNull();
  } finally { vi.useRealTimers(); }
});
it("notes calmly when the Vault changed since the explanation was written", async () => {
  vi.mocked(workspaceApi.getPath).mockResolvedValue({ ...pathResult, stale: true });
  render(<PathPage id="path-one" onBack={vi.fn()} onPlaces={vi.fn()} onChat={vi.fn()} />);
  expect(await screen.findByText("Your Vault changed since PAI wrote this, so parts of it may be out of date.")).toBeTruthy();
});
it("says nothing about age when the explanation is current", async () => {
  vi.mocked(workspaceApi.getPath).mockResolvedValue({ ...pathResult, stale: false });
  render(<PathPage id="path-one" onBack={vi.fn()} onPlaces={vi.fn()} onChat={vi.fn()} />);
  await screen.findByRole("heading", { level: 1 });
  expect(screen.queryByText(/may be out of date/)).toBeNull();
});
