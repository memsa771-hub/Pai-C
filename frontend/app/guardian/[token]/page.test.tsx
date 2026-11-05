// @vitest-environment jsdom
import { it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { Suspense } from "react";
import { I18nProvider } from "@/lib/i18n";
import messages from "@/lib/i18n/messages/en-US";
import GuardianPageRoute from "./page";

vi.mock("next/image", () => ({ default: (p: { alt: string }) => <span>{p.alt}</span> }));

const TOKEN = "tok-abc_123";
const agreeText = { title: "Sam asks for your agreement", body: ["Sam chose a study route.", "Nothing else is shared."], agree_button: "I agree" };
const g = messages.guardian;

type Reply = { status?: number; data?: unknown };
const ok = (data: unknown): Reply => ({ data });
const page = (state: string, withText = state === "ok") => ok({ state, student_first_name: "Sam", text: withText ? agreeText : null });

/** The API by route: "GET " + path after the token, "POST " + path. */
function api(routes: Record<string, Reply>) {
  const calls: { url: string; init: RequestInit }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    calls.push({ url, init });
    const key = `${init.method ?? "GET"} ${url.split(TOKEN)[1]}`;
    const r = routes[key];
    if (!r) throw new Error(`no route for ${key}`);
    return { ok: (r.status ?? 200) < 400, status: r.status ?? 200, json: async () => ({ code: 0, message: "ok", data: r.data }) };
  }));
  return calls;
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

// A promise React reads at once (it marks it as settled), so the page renders without a Suspense round trip.
const params = Object.assign(Promise.resolve({ token: TOKEN }), { status: "fulfilled", value: { token: TOKEN } });
async function open() {
  return render(
    <I18nProvider>
      <Suspense fallback={null}>
        <GuardianPageRoute params={params} />
      </Suspense>
    </I18nProvider>);
}
const message = async (title: string) => {
  await waitFor(() => expect(screen.getByTestId("guardian-message").textContent).toContain(title));
};

// req: R-10 R-79
it("shows the approved text with an Agree button, and agrees only when the button is pressed", async () => {
  const calls = api({ "GET ": page("ok"), "POST /agree": ok({ state: "agreed" }) });
  await open();
  await screen.findByRole("heading", { name: agreeText.title });
  agreeText.body.forEach((line) => expect(screen.getByText(line)).toBeTruthy());
  expect(calls.map((c) => c.init.method ?? "GET")).toEqual(["GET"]); // opening the page changes nothing
  fireEvent.click(screen.getByRole("button", { name: agreeText.agree_button }));
  await message(g.agreedTitle);
  expect(calls.map((c) => `${c.init.method ?? "GET"} ${c.url.split(TOKEN)[1]}`)).toEqual(["GET ", "POST /agree"]);
});

// req: R-10 R-79
it("sends no referrer, keeps the token in the path only, and stores nothing", async () => {
  const calls = api({ "GET ": page("ok"), "POST /agree": ok({ state: "agreed" }) });
  await open();
  fireEvent.click(await screen.findByRole("button", { name: agreeText.agree_button }));
  await message(g.agreedTitle);
  for (const { url, init } of calls) {
    expect(init.referrerPolicy).toBe("no-referrer");
    expect(init.credentials).toBe("omit");
    expect(init.headers).toBeUndefined();
    expect(url).toMatch(new RegExp(`/v1/guardian/${TOKEN}(/agree)?$`));
    expect(url).not.toContain("?");
  }
  expect(window.localStorage.length + window.sessionStorage.length).toBe(0);
});

// req: R-10 R-79
it.each([
  ["expired", g.expiredTitle],
  ["used", g.usedTitle],
  ["stale", g.staleTitle],
])("says so for a %s link and offers no button", async (state, title) => {
  api({ "GET ": page(state), "GET /withdraw": page("expired") });
  await open();
  await message(title);
  expect(screen.queryByRole("button")).toBeNull();
});

// req: R-10 R-79
it("a used agree link is never looked up as a withdraw link", async () => {
  const calls = api({ "GET ": page("used") });
  await open();
  await message(g.usedTitle);
  expect(calls).toHaveLength(1);
});

// req: R-10 R-79
it("the confirmation mail's link opens the withdraw page and withdraws on the button", async () => {
  const calls = api({ "GET ": page("expired"), "GET /withdraw": page("ok"), "POST /withdraw": ok({ state: "withdrawn" }) });
  await open();
  await screen.findByRole("heading", { name: g.withdrawTitle.replace("{name}", "Sam") });
  expect(screen.queryByRole("button", { name: agreeText.agree_button })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: g.withdrawButton }));
  await message(g.withdrawnTitle);
  expect(calls.map((c) => `${c.init.method ?? "GET"} ${c.url.split(TOKEN)[1]}`)).toEqual(["GET ", "GET /withdraw", "POST /withdraw"]);
});

// req: R-10 R-79
it("a withdraw link that was already used says so", async () => {
  api({ "GET ": page("expired"), "GET /withdraw": page("used") });
  await open();
  await message(g.usedTitle);
});

// req: R-10 R-79
it("reaches the withdraw page even while agreeing is paused (409)", async () => {
  api({ "GET ": { status: 409 }, "GET /withdraw": page("ok") });
  await open();
  await screen.findByRole("button", { name: g.withdrawButton });
});

// req: R-10 R-79
it("shows a state the click answers (a link that expired meanwhile)", async () => {
  api({ "GET ": page("ok"), "POST /agree": ok({ state: "expired" }) });
  await open();
  fireEvent.click(await screen.findByRole("button", { name: agreeText.agree_button }));
  await message(g.expiredTitle);
});

// req: R-10 R-79
it.each([
  [429, g.busyTitle],
  [409, g.unavailableTitle],
  [500, g.errorTitle],
])("shows a calm message for HTTP %s", async (status, title) => {
  api({ "GET ": { status }, "GET /withdraw": { status } });
  await open();
  await message(title);
});

// req: R-10 R-79
it("shows the error message when the network fails", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("offline"); }));
  await open();
  await message(g.errorTitle);
});

// req: R-10 R-79
it("sets the no-referrer meta through the layout", async () => {
  const { metadata } = await import("./layout");
  expect(metadata.referrer).toBe("no-referrer");
});
