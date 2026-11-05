// @vitest-environment jsdom
import { it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup, within } from "@testing-library/react";
import { I18nProvider } from "@/lib/i18n";
import { workspaceApi } from "@/lib/api";
import { ChoiceFlow } from "./choice-flow";
import { placeName } from "./choice-text";
import { chosenRoute, choiceOptionsOn, offeredPlaces, roadmapCards, routeChoice } from "@/tests/fixtures/counselor";
import copy from "./copy.json";

vi.mock("@/lib/api", () => ({
  workspaceApi: { chooseRoute: vi.fn(), places: vi.fn(), resendGuardian: vi.fn() },
}));
const c = copy.roadmap.choice;
const DE = new RegExp(placeName("DE"));
const onSaved = vi.fn(), onClose = vi.fn(), onOpenVault = vi.fn();

afterEach(() => { cleanup(); vi.clearAllMocks(); });
beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn(); // jsdom has none; the date picker scrolls its year grid
  vi.mocked(workspaceApi.places).mockResolvedValue({ handoff: true, places: offeredPlaces });
  vi.mocked(workspaceApi.chooseRoute).mockResolvedValue({ ...chosenRoute, choice: routeChoice() });
});

const open = (over: Partial<typeof choiceOptionsOn> = {}) => render(
  <I18nProvider>
    <ChoiceFlow card={roadmapCards[0]} options={{ ...choiceOptionsOn, ...over }} onSaved={onSaved} onClose={onClose} onOpenVault={onOpenVault} />
  </I18nProvider>);
const next = () => fireEvent.click(screen.getByRole("button", { name: c.next }));
const heading = () => screen.getByTestId("choice-step").textContent;
const pickCountry = (name: RegExp) => fireEvent.click(screen.getByRole("radio", { name }));
const pickIntake = (term = "winter", year = "2027") => {
  fireEvent.change(screen.getByLabelText(c.intake.term), { target: { value: term } });
  fireEvent.change(screen.getByLabelText(c.intake.year), { target: { value: year } });
};
async function toPlaces() {
  open();
  pickCountry(DE); next();
  pickIntake(); next();
  await screen.findByRole("checkbox", { name: "Alpha University" });
}
const pickPlace = (name: string) => fireEvent.click(screen.getByRole("checkbox", { name }));
const agree = () => fireEvent.click(screen.getByRole("checkbox", { name: c.consent.agree }));

// req: R-79
it("walks destination, intake, places and consent in order, and shows the API's consent text", async () => {
  await toPlaces();
  expect(heading()).toBe("Step 3 of 4: Places");
  pickPlace("Alpha University"); next();
  expect(heading()).toBe("Step 4 of 4: Consent");
  expect(screen.getByText(choiceOptionsOn.consent_text!)).toBeTruthy();
  // The step list names every step and marks where the student is.
  const steps = within(screen.getByRole("list", { name: c.progress })).getAllByRole("listitem");
  expect(steps.map((li) => li.textContent)).toEqual(["Country", "Intake", "Places", "Consent"].map((n) => expect.stringContaining(n)) as unknown as string[]);
  expect(steps[3].getAttribute("aria-current")).toBe("step");
  fireEvent.click(screen.getByRole("button", { name: c.back }));
  expect(heading()).toBe("Step 3 of 4: Places");
});

// req: R-79
it("offers only the countries and terms the API sends", async () => {
  open();
  expect(screen.getAllByRole("radio")).toHaveLength(2);
  pickCountry(DE); next();
  const terms = within(screen.getByLabelText(c.intake.term)).getAllByRole("option").map((o) => (o as HTMLOptionElement).value).filter(Boolean);
  expect(terms).toEqual(["winter", "summer"]);
});

// req: R-79
it("lets the student pick at most 5 places and put them in order", async () => {
  await toPlaces();
  for (const name of ["Alpha University", "Beta Institute", "Gamma College", "Delta University", "Epsilon School"]) pickPlace(name);
  expect((screen.getByRole("checkbox", { name: "Zeta Academy" }) as HTMLInputElement).disabled).toBe(true);
  const order = () => within(screen.getByRole("list", { name: c.places.ranking })).getAllByRole("listitem").map((li) => li.textContent);
  expect(order()[0]).toContain("1. Alpha University");
  fireEvent.click(screen.getByRole("button", { name: "Move Beta Institute up" }));
  expect(order().slice(0, 2)).toEqual([expect.stringContaining("1. Beta Institute"), expect.stringContaining("2. Alpha University")]);
  // The first cannot go up and the last cannot go down.
  expect((screen.getByRole("button", { name: "Move Beta Institute up" }) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole("button", { name: "Move Epsilon School down" }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Remove Gamma College" }));
  expect(order()).toHaveLength(4);
});

// req: R-79
it("sends exactly the picked details to chooseRoute", async () => {
  await toPlaces();
  pickPlace("Alpha University"); pickPlace("Gamma College");
  fireEvent.click(screen.getByRole("button", { name: "Move Gamma College up" }));
  next(); agree();
  fireEvent.click(screen.getByRole("button", { name: c.submit }));
  await waitFor(() => expect(workspaceApi.chooseRoute).toHaveBeenCalledTimes(1));
  expect(workspaceApi.chooseRoute).toHaveBeenCalledWith("electrical_engineering", {
    destination: "DE", intake: { term: "winter", year: 2027 },
    places: [{ ref: "p3", rank: 1 }, { ref: "p1", rank: 2 }], consent: true,
  });
  expect(workspaceApi.places).toHaveBeenCalledWith("DE", "bachelor", "winter", 2027);
  await waitFor(() => expect(onSaved).toHaveBeenCalled());
  expect(onClose).toHaveBeenCalled(); // no guardian email, nothing more to say
});

// req: R-79
it("asks for the date of birth only when the Vault has none", async () => {
  open({ needs_dob: true });
  pickCountry(DE); next();
  pickIntake(); next();
  await screen.findByRole("checkbox", { name: "Alpha University" });
  pickPlace("Alpha University"); next();
  expect(heading()).toBe("Step 4 of 5: Date of birth");
  next(); // empty: an error, and focus goes to the picker
  expect(screen.getByRole("alert").textContent).toContain(c.dob.required);
  expect(document.activeElement).toBe(screen.getByRole("button", { name: /date of birth/i }));
});

// req: R-10
it("requires the guardian email when the date of birth makes the student under 18", async () => {
  const year = new Date().getFullYear() - 15;
  open({ needs_dob: true });
  pickCountry(DE); next();
  pickIntake(); next();
  await screen.findByRole("checkbox", { name: "Alpha University" });
  pickPlace("Alpha University"); next();
  fireEvent.click(screen.getByRole("button", { name: /date of birth/i }));
  fireEvent.click(await screen.findByRole("option", { name: String(year) }));
  fireEvent.click(await screen.findByRole("option", { name: "Jan" }));
  fireEvent.click(await screen.findByRole("button", { name: new RegExp(`January 1, ${year}`) }));
  next(); agree(); next();
  expect(heading()).toBe("Step 6 of 6: Parent or guardian");
  fireEvent.click(screen.getByRole("button", { name: c.submit }));
  // No email: nothing is sent, the error is shown and focus is on the field.
  expect(workspaceApi.chooseRoute).not.toHaveBeenCalled();
  expect(document.activeElement).toBe(screen.getByLabelText(c.guardian.label));
  expect(screen.getByRole("alert").textContent).toContain(c.guardian.required);
  fireEvent.change(screen.getByLabelText(c.guardian.label), { target: { value: "parent@example.com" } });
  fireEvent.click(screen.getByRole("button", { name: c.submit }));
  await waitFor(() => expect(workspaceApi.chooseRoute).toHaveBeenCalledTimes(1));
  expect(vi.mocked(workspaceApi.chooseRoute).mock.calls[0][1]).toEqual({
    destination: "DE", intake: { term: "winter", year: 2027 }, places: [{ ref: "p1", rank: 1 }], consent: true,
    date_of_birth: `${year}-01-01`, guardian_email: "parent@example.com",
  });
});

// req: R-10
it("adds the guardian step when the API says a stored date of birth is under 18", async () => {
  await toPlaces();
  pickPlace("Alpha University"); next(); agree();
  vi.mocked(workspaceApi.chooseRoute).mockRejectedValueOnce(
    new Error('API 422: {"detail":"You are under 18: a parent or guardian\'s email address is needed"}'));
  fireEvent.click(screen.getByRole("button", { name: c.submit }));
  await waitFor(() => expect(heading()).toBe("Step 5 of 5: Parent or guardian"));
  expect(document.activeElement).toBe(screen.getByLabelText(c.guardian.label));
  fireEvent.change(screen.getByLabelText(c.guardian.label), { target: { value: "parent@example.com" } });
  fireEvent.click(screen.getByRole("button", { name: c.submit }));
  await waitFor(() => expect(workspaceApi.chooseRoute).toHaveBeenCalledTimes(2));
  expect(vi.mocked(workspaceApi.chooseRoute).mock.calls[1][1]).toMatchObject({ guardian_email: "parent@example.com" });
});

// req: R-10
it("will not go past consent until the box is ticked, and moves focus to it", async () => {
  await toPlaces();
  pickPlace("Alpha University"); next();
  fireEvent.click(screen.getByRole("button", { name: c.submit }));
  expect(workspaceApi.chooseRoute).not.toHaveBeenCalled();
  expect(screen.getByRole("alert").textContent).toContain(c.consent.required);
  expect(document.activeElement).toBe(screen.getByRole("checkbox", { name: c.consent.agree }));
});

// req: R-10
it("blocks consent while the text is not approved", async () => {
  open({ consent_text: null });
  pickCountry(DE); next(); pickIntake(); next();
  await screen.findByRole("checkbox", { name: "Alpha University" });
  pickPlace("Alpha University"); next();
  expect(screen.getByText(c.consent.unavailable)).toBeTruthy();
  expect(screen.queryByRole("checkbox", { name: c.consent.agree })).toBeNull();
  expect(screen.queryByRole("button", { name: c.submit })).toBeNull();
});

// req: R-79
it("focuses the first error: no country, no term, no place", async () => {
  open();
  next();
  expect(screen.getByRole("alert").textContent).toContain(c.destination.required);
  expect(document.activeElement).toBe(screen.getAllByRole("radio")[0]);
  pickCountry(DE); next();
  next();
  expect(document.activeElement).toBe(screen.getByLabelText(c.intake.term));
  expect(screen.getByLabelText(c.intake.term).getAttribute("aria-invalid")).toBe("true");
  pickIntake(); next();
  await screen.findByRole("checkbox", { name: "Alpha University" });
  next();
  expect(screen.getByRole("alert").textContent).toContain(c.places.empty);
  expect(document.activeElement).toBe(screen.getByRole("checkbox", { name: "Alpha University" }));
});

// req: R-10
it("points to the Vault when the date of birth there needs confirming", async () => {
  await toPlaces();
  pickPlace("Alpha University"); next(); agree();
  vi.mocked(workspaceApi.chooseRoute).mockRejectedValueOnce(
    new Error('API 409: {"detail":"Confirm your date of birth in your Vault first"}'));
  fireEvent.click(screen.getByRole("button", { name: c.submit }));
  expect((await screen.findByRole("alert")).textContent).toContain("Confirm your date of birth in your Vault first");
  fireEvent.click(screen.getByRole("button", { name: c.dob.vault }));
  expect(onOpenVault).toHaveBeenCalled();
  expect(onSaved).not.toHaveBeenCalled();
});

// req: R-10
it("says the guardian email was not sent and sends it again to an address typed again", async () => {
  await toPlaces();
  pickPlace("Alpha University"); next(); agree();
  vi.mocked(workspaceApi.chooseRoute).mockResolvedValueOnce({ ...chosenRoute, choice: routeChoice({ consent: { student: "given", guardian: "missing" } }), guardian_email_sent: false });
  vi.mocked(workspaceApi.resendGuardian).mockResolvedValue({ sent: true });
  fireEvent.click(screen.getByRole("button", { name: c.submit }));
  expect((await screen.findByText(new RegExp(c.done.notSent))).textContent).toContain(c.done.notSent);
  expect(onSaved).toHaveBeenCalledTimes(1);
  expect(onClose).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText(copy.roadmap.choice.consentState.resendLabel), { target: { value: "parent@example.com" } });
  fireEvent.click(screen.getByRole("button", { name: copy.roadmap.choice.consentState.resendSend }));
  await waitFor(() => expect(workspaceApi.resendGuardian).toHaveBeenCalledWith("parent@example.com"));
  expect(await screen.findByText(copy.roadmap.choice.consentState.resendSent)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: c.done.button }));
  expect(onClose).toHaveBeenCalled();
});

// req: R-79
it("keeps the student on the step with a message when saving fails", async () => {
  await toPlaces();
  pickPlace("Alpha University"); next(); agree();
  vi.mocked(workspaceApi.chooseRoute).mockRejectedValueOnce(new Error("API 500: boom"));
  fireEvent.click(screen.getByRole("button", { name: c.submit }));
  expect((await screen.findByRole("alert")).textContent).toContain(c.error);
  expect(onSaved).not.toHaveBeenCalled();
  expect(heading()).toBe("Step 4 of 4: Consent");
});
