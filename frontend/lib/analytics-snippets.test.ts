import { it, expect } from "vitest";
import { gaSnippet, isPrivatePath, posthogSnippet } from "./analytics-snippets";

type Win = { location: { pathname: string }; posthog?: { _i: [string, Record<string, unknown>][] }; dataLayer?: unknown[] };

/** Runs a snippet the way the browser does, against a bare window and document. */
function run(source: string, pathname: string) {
  const win: Win = { location: { pathname } };
  const appended: unknown[] = [];
  const doc = {
    createElement: () => ({}),
    getElementsByTagName: () => [{ parentNode: { insertBefore: () => {} } }],
    head: { appendChild: (n: unknown) => appended.push(n) },
  };
  new Function("window", "document", source)(win, doc);
  return { win, appended };
}

// req: R-10 R-79
it("knows the paths that carry a token", () => {
  expect(isPrivatePath("/guardian/abc")).toBe(true);
  expect(isPrivatePath("/share/abc")).toBe(true);
  expect(isPrivatePath("/sign-in")).toBe(false);
  expect(isPrivatePath("/guardian")).toBe(false);
});

// req: R-10 R-79
it.each(["/guardian/secret-token", "/share/secret-token"])("PostHog is not even loaded on %s", (path) => {
  expect(run(posthogSnippet("phc_key", "https://ph.example"), path).win.posthog).toBeUndefined();
});

// req: R-10 R-79
it("PostHog starts elsewhere, and its before_send drops events that come up on a token page", () => {
  const { win } = run(posthogSnippet("phc_key", "https://ph.example"), "/sign-in");
  const [, options] = win.posthog!._i[0];
  expect(options.capture_pageview).toBe("history_change");
  const beforeSend = options.before_send as (e: object) => object | null;
  expect(beforeSend({ event: "$pageview" })).toEqual({ event: "$pageview" });
  win.location.pathname = "/guardian/secret-token"; // a client-side move onto the page
  expect(beforeSend({ event: "$pageview" })).toBeNull();
});

// req: R-10 R-79
it("Google Analytics loads and counts elsewhere, never on a token page", () => {
  const ok = run(gaSnippet("G-TEST"), "/sign-in");
  expect(ok.appended).toHaveLength(1);
  expect(ok.win.dataLayer!.length).toBe(2);
  for (const path of ["/guardian/secret-token", "/share/secret-token"]) {
    const blocked = run(gaSnippet("G-TEST"), path);
    expect(blocked.appended).toHaveLength(0);
    expect(blocked.win.dataLayer).toBeUndefined();
  }
});
