// @vitest-environment jsdom
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup, within } from "@testing-library/react";
import { Mirror } from "./mirror";
import { MirrorLink } from "../mirror-link";
import { workspaceApi } from "@/lib/api";
import { mirrorCard, mirrorEmpty } from "@/tests/fixtures/counselor";
import copy from "./copy.json";

vi.mock("@/lib/api", () => ({ workspaceApi: { getMirror: vi.fn() } }));
afterEach(() => { cleanup(); vi.clearAllMocks(); window.history.replaceState({}, "", "/student"); });
beforeEach(() => { vi.mocked(workspaceApi.getMirror).mockResolvedValue(structuredClone(mirrorCard)); });

const tile = async (label: string) => (await screen.findByRole("heading", { level: 3, name: label })).closest("article")!;

it("draws the student first: name, education line and when it was updated", async () => {
  render(<Mirror onChat={vi.fn()} />);
  expect(await screen.findByRole("heading", { level: 1, name: "Sam Taylor" })).toBeTruthy();
  expect(screen.getAllByText("FSc Pre-Engineering, 78%").length).toBeGreaterThan(0);
  expect(screen.getByText("Updated Oct 27, 2026")).toBeTruthy();
  expect(screen.getByText("7 of 10 areas known")).toBeTruthy();
  // The text sits under the header, as written; never a question.
  for (const sentence of mirrorCard.text!.sentences) expect(screen.getByText(sentence)).toBeTruthy();
});

it("shows each known area with a level bar, its entries, badges and sources", async () => {
  render(<Mirror onChat={vi.fn()} />);
  const history = await tile("Education & experience");
  expect(within(history).getByRole("meter", { name: "How well PAI knows this: Well shown" }).getAttribute("aria-valuenow")).toBe("3");
  expect(within(history).getByText("From document")).toBeTruthy();
  expect(within(history).getByText("Result card.jpg")).toBeTruthy();
  expect(within(history).getByText("Confirmed")).toBeTruthy();
  // Subject marks as bars.
  expect(within(history).getByRole("meter", { name: "Physics: 81%" })).toBeTruthy();
  const strengths = await tile("Strengths");
  expect(within(strengths).getByText("PAI's guess")).toBeTruthy();
  expect(within(strengths).getByRole("meter", { name: "How well PAI knows this: Said, not shown" })).toBeTruthy();
  // Unknown areas are not tiles; they are in the Still unknown list.
  expect(screen.queryByRole("heading", { level: 3, name: "Values" })).toBeNull();
});

it("marks a tension on both areas, with both sides, and resolves nothing", async () => {
  render(<Mirror onChat={vi.fn()} />);
  const note = mirrorCard.areas[1].tension.length && copy.mirror.templates["tension.family_vs_goal"];
  for (const label of ["Family", "Goals & whose wish"]) {
    const area = await tile(label);
    expect(within(area).getByText(note as string)).toBeTruthy();
  }
  // Each side's entry carries the marker.
  expect(screen.getByText("Mother, wishes MBBS").closest("li")!.querySelector("[data-tension]")).toBeTruthy();
  expect(screen.getByText("Become an electrical engineer").closest("li")!.querySelector("[data-tension]")).toBeTruthy();
});

it("lists what is still unknown with the question, and Tell PAI opens chat on that topic", async () => {
  const chat = vi.fn();
  render(<Mirror onChat={chat} />);
  const list = await screen.findByRole("region", { name: "Still unknown" });
  expect(within(list).getAllByRole("listitem")).toHaveLength(3);
  expect(within(list).getByText(copy.mirror.questions["topic_text.pressures"].question)).toBeTruthy();
  fireEvent.click(within(list).getByRole("button", { name: "Tell PAI about Pressures & limits" }));
  expect(chat).toHaveBeenCalledWith(copy.mirror.questions["topic_text.pressures"].topic);
});

it("This is wrong opens the Vault entry: Details for a fact or record, the story for an item", async () => {
  const open = vi.fn();
  render(<Mirror onChat={vi.fn()} onOpenEntry={open} />);
  fireEvent.click(await screen.findByRole("button", { name: "This is wrong: FSc Pre-Engineering, 78%" }));
  expect(open).toHaveBeenLastCalledWith("education:education");
  fireEvent.click(screen.getByRole("button", { name: "This is wrong: Mother, wishes MBBS" }));
  expect(open).toHaveBeenLastCalledWith("item:parent");
});

it("opens the Vault by URL by default, with the story tab for an item", async () => {
  const pop = vi.fn();
  window.addEventListener("popstate", pop);
  render(<Mirror onChat={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "This is wrong: Current situation: Studying" }));
  expect(Object.fromEntries(new URLSearchParams(window.location.search))).toEqual({ view: "profile", entry: "fact:identity.current_status" });
  fireEvent.click(screen.getByRole("button", { name: "This is wrong: Fixing things" }));
  expect(Object.fromEntries(new URLSearchParams(window.location.search))).toEqual({ view: "profile", entry: "item:fixing", tab: "background" });
  expect(pop).toHaveBeenCalledTimes(2);
  window.removeEventListener("popstate", pop);
});

it("says PAI needs a little more when the picture is not ready, with the first unknown", async () => {
  vi.mocked(workspaceApi.getMirror).mockResolvedValue(structuredClone(mirrorEmpty));
  const chat = vi.fn();
  render(<Mirror onChat={chat} />);
  const empty = await screen.findByRole("region", { name: copy.mirror.emptyTitle });
  expect(within(empty).getByText(copy.mirror.questions["topic_text.goals"].question)).toBeTruthy();
  fireEvent.click(within(empty).getByRole("button", { name: "Tell PAI about Goals & whose wish" }));
  expect(chat).toHaveBeenCalledWith(copy.mirror.questions["topic_text.goals"].topic);
  // It still shows the areas it has.
  expect(await tile("Education & experience")).toBeTruthy();
  expect(screen.getByText("2 of 10 areas known")).toBeTruthy();
  expect(screen.queryByText(copy.mirror.inWords)).toBeNull();
});

it("fits a 375px phone: tiles shrink and long words wrap", async () => {
  const { container } = render(<Mirror onChat={vi.fn()} />);
  await tile("Interests");
  for (const article of container.querySelectorAll("article")) expect(article.className).toMatch(/\bmin-w-0\b/);
  for (const text of container.querySelectorAll("[data-entry-text]")) expect(text.className).toMatch(/\bbreak-words\b/);
  // No fixed width wider than a phone's content box.
  const widths = [...container.querySelectorAll("[class]")].flatMap((el) => [...String(el.getAttribute("class")).matchAll(/\b(?:min-)?w-\[(\d+)px\]/g)].map((m) => +m[1]));
  expect(widths.every((w) => w <= 343)).toBe(true);
  expect(container.innerHTML).not.toMatch(/\b(?:min-w|w)-(?:96|80|72)\b/);
});

it("has a template for every backend Mirror copy key and a question for every area", () => {
  const backend = resolve(__dirname, "../../../../backend/app/pai_c/policy");
  const policy = JSON.parse(readFileSync(join(backend, "mirror.json"), "utf8"));
  expect(copy.mirror.templates).toEqual(policy.copy);
  const areas = JSON.parse(readFileSync(join(backend, "areas_policy.json"), "utf8"));
  expect(Object.keys(copy.mirror.questions).sort()).toEqual([...new Set(Object.values(areas.questions) as string[])].sort());
  for (const tension of policy.tension) expect(copy.mirror.templates).toHaveProperty([tension.note_key]);
});

it("links to the Mirror from a chat card", () => {
  render(<MirrorLink header={mirrorCard.header} />);
  expect(screen.getByText("Sam Taylor · FSc Pre-Engineering, 78%")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Open your Mirror" }));
  expect(new URLSearchParams(window.location.search).get("view")).toBe("mirror");
});

it("imports none of the removed Mirror components", () => {
  const root = resolve(__dirname, "../../..");
  const files: string[] = [];
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      if (["node_modules", ".next", "dist", "out"].includes(name)) continue;
      const path = join(dir, name);
      if (statSync(path).isDirectory()) walk(path);
      else if (/\.(tsx?|cjs|mjs)$/.test(name) && !path.endsWith("mirror.test.tsx")) files.push(path);
    }
  };
  for (const dir of ["app", "components", "lib", "tests"]) walk(join(root, dir));
  const removed = /counselor-mirror-card|lib\/counselor-mirror\b|\bMirrorPanel\b|\bFeltUnderstood\b|getCounselorSummary|counselorMirror\./;
  expect(files.filter((file) => removed.test(readFileSync(file, "utf8")))).toEqual([]);
});
