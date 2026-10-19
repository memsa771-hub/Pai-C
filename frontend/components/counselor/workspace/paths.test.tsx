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
    screen.getByRole("button", { name: "Where could I study this?" }),
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
