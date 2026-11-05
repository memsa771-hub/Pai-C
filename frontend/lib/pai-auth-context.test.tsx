// @vitest-environment jsdom
import { it, expect, vi, afterEach } from "vitest";
import { render, cleanup, waitFor } from "@testing-library/react";

const onUserChange = vi.fn((cb: (u: null) => void) => { cb(null); return () => {}; });
vi.mock("./auth/service", () => ({
  AUTH_INVALID_EVENT: "x", AUTH_UNVERIFIED_EVENT: "y", FIREBASE_SESSION: "s",
  onUserChange: (cb: (u: null) => void) => onUserChange(cb),
  signedInUser: () => null, signOut: vi.fn(), startSession: vi.fn(),
}));
vi.mock("./analytics", () => ({ identify: vi.fn(), resetIdentity: vi.fn() }));
vi.mock("./api", () => ({ workspaceApi: { reset: vi.fn() } }));

import { PaiAuthProvider } from "./pai-auth-context";

const replace = vi.fn();
function visit(pathname: string) {
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { hostname: "localhost", pathname, replace, assign: vi.fn() },
  });
  return render(<PaiAuthProvider><p>page</p></PaiAuthProvider>);
}
afterEach(() => { cleanup(); vi.clearAllMocks(); });

// req: R-10 R-79
it.each(["/guardian/abc", "/share/abc"])("leaves %s alone for a signed-out visitor", async (path) => {
  visit(path);
  await waitFor(() => expect(document.getElementById("pai-session-shield")!.style.display).toBe("none"));
  expect(replace).not.toHaveBeenCalled();
  expect(onUserChange).not.toHaveBeenCalled();
});

// req: R-10 R-79
it("still sends a signed-out visitor of a private page to sign-in", async () => {
  visit("/some-workspace");
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/sign-in"));
});
