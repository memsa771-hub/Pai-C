/** Opens a workspace view from anywhere, chat included. The shell reads the
 * view from the URL on popstate, so links need no access to its state. */
export function openWorkspaceView(view: string, params: Record<string, string> = {}) {
  const base = "/" + window.location.pathname.split("/").filter(Boolean)[0];
  window.history.pushState({}, "", `${base}?${new URLSearchParams({ view, ...params })}`);
  window.dispatchEvent(new PopStateEvent("popstate"));
}
