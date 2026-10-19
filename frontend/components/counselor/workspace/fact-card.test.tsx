// @vitest-environment jsdom
import { it, expect, vi, afterEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  cleanup,
} from "@testing-library/react";
import { FactCard } from "./fact-card";
import { workspaceApi } from "@/lib/api";
vi.mock("@/lib/api", () => ({ workspaceApi: { answerFactCard: vi.fn() } }));
vi.mock("@/components/layout/layout-context", () => ({
  useLayout: () => ({ openView: vi.fn() }),
}));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
it("offers only catalog choices and Other; requires confirmation before saving", async () => {
  render(
    <FactCard
      card={{
        key: "board",
        label: "Awarding body",
        kind: "choice",
        choices: [{ value: "catalog", label: "Catalog body" }],
        prefill: { value: "catalog", quote: "I studied with catalog" },
      }}
    />,
  );
  expect(workspaceApi.answerFactCard).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Other" }));
  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: "My own words" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Confirm this answer" }));
  await waitFor(() =>
    expect(workspaceApi.answerFactCard).toHaveBeenCalledWith(
      "board",
      expect.objectContaining({
        value: "My own words",
        other: true,
        confirmed: true,
      }),
    ),
  );
  expect(await screen.findByRole("status")).toBeTruthy();
});
it("shows retryable errors without claiming a save", async () => {
  vi.mocked(workspaceApi.answerFactCard).mockRejectedValueOnce(new Error());
  render(
    <FactCard
      card={{ key: "city", label: "City", kind: "text", choices: [] }}
    />,
  );
  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: "My city" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Confirm this answer" }));
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(screen.queryByText("Saved")).toBeNull();
});
