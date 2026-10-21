// @vitest-environment jsdom
import { it, expect, vi, afterEach } from "vitest";
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
    analyzePaths: vi.fn(),
  },
}));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
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
it("adds the student's own path and asks PAI to find paths", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.mocked(workspaceApi.getPossibilities).mockResolvedValue(possibilities);
  vi.mocked(workspaceApi.addOwnPath).mockResolvedValue({ ...possibilities[1], id: "mine", title: "Nursing" });
  vi.mocked(workspaceApi.analyzePaths).mockResolvedValue({ job_id: "job" });
  render(<Paths onOpen={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Add your own path" }));
  const add = screen.getByRole("button", { name: "Add path" }) as HTMLButtonElement;
  expect(add.disabled).toBe(true);
  fireEvent.change(screen.getByLabelText("Path"), { target: { value: "  Nursing " } });
  fireEvent.change(screen.getByLabelText("Why it interests you (optional)"), { target: { value: "I like caring" } });
  fireEvent.click(add);
  await waitFor(() => expect(workspaceApi.addOwnPath).toHaveBeenCalledWith("Nursing", "I like caring"));
  expect(await screen.findByRole("status")).toBeTruthy();
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(vi.mocked(workspaceApi.getPossibilities).mock.calls.length).toBeGreaterThan(2);
  cleanup();
  render(<Paths onOpen={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Find my paths" }));
  await waitFor(() => expect(workspaceApi.analyzePaths).toHaveBeenCalledOnce());
  expect((screen.getByRole("button", { name: "Find my paths" }) as HTMLButtonElement).disabled).toBe(true);
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

it('expired evidence requires fresh consent and cannot prepare a roadmap',async()=>{
 vi.mocked(workspaceApi.getPrograms).mockResolvedValue({status:'stale',programs:[],missing:['expired_sources']});
 render(<ProgramPage id='path-one' onBack={vi.fn()}/>);
 const button=await screen.findByRole('button',{name:'Look at programs'});
 expect((button as HTMLButtonElement).disabled).toBe(true);
 expect(screen.queryByRole('button',{name:'Prepare a reviewed roadmap'})).toBeNull();
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
