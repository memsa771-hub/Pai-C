// @vitest-environment jsdom
import { it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { useState } from "react";
import { ValueEditor } from "./profile-details";
import { choicesFor, withChoiceLabels, type VaultCatalogType } from "@/lib/vault";

vi.mock("@/lib/workspace-context", () => ({ useWorkspace: () => ({ setSelectedFileId: vi.fn() }) }));
afterEach(cleanup);

const education: VaultCatalogType = {
  key: "education", label: "Education", storage: "record", shown_on: "details", section: "education",
  inputs: ["chat", "document", "details"], schema: null,
  choices: {
    qualification_name: [{ code: "fsc", label: "FSc" }, { code: "bachelor", label: "Bachelor" }, { code: "matric", label: "Matric" }],
    field_of_study: [{ code: "pre_medical", label: "Pre-Medical" }, { code: "pre_engineering", label: "Pre-Engineering" }],
  },
  choice_by_level: { field_of_study: {
    bachelor: [{ code: "computer_science", label: "Computer Science" }, { code: "bba", label: "BBA" }],
    matric: [{ code: "science_biology", label: "Science (Biology)" }, { code: "arts", label: "Arts" }],
  } },
};

function Editor({ initial }: { initial: Record<string, unknown> }) {
  const [value, setValue] = useState<unknown>(initial);
  return <ValueEditor value={value} onChange={setValue} label="Education" choices={choicesFor(education, value)} />;
}

const options = (name: string) =>
  [...(screen.getByRole("combobox", { name }) as HTMLSelectElement).options].map((o) => o.textContent);

it("edits a Bachelor's field with study fields, never intermediate groups", () => {
  render(<Editor initial={{ qualification_name: "bachelor", field_of_study: "computer_science" }} />);
  expect(options("Field of study")).toEqual(["Choose", "Computer Science", "BBA"]);
  expect(options("Field of study")).not.toContain("Pre-Medical");
});

it("follows the draft's level as it changes", () => {
  render(<Editor initial={{ qualification_name: "fsc", field_of_study: "pre_medical" }} />);
  expect(options("Field of study")).toEqual(["Choose", "Pre-Medical", "Pre-Engineering"]);
  fireEvent.change(screen.getByRole("combobox", { name: "Qualification" }), { target: { value: "matric" } });
  expect(options("Field of study")).toEqual(["Choose", "Science (Biology)", "Arts"]);
});

it("reads a level-aware code as its label", () => {
  expect(withChoiceLabels({ qualification_name: "bachelor", field_of_study: "computer_science" }, education))
    .toEqual({ qualification_name: "Bachelor", field_of_study: "Computer Science" });
  expect(choicesFor(education, { qualification_name: "Bachelor" }).field_of_study[0].code).toBe("computer_science");
});
