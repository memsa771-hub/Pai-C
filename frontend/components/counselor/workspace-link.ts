/** Section names land on the section's first view; old view names (roadmaps,
 * and the Compare and Plan tabs) land on the one Roadmap page. Shared by the
 * shell's URL reader and chat place links. */
export const VIEW_ALIASES: Record<string, string> = {
  roadmaps: "roadmap", compare: "roadmap", plan: "roadmap", vault: "files", pai: "threads", home: "overview",
};

/** Opens a workspace view from anywhere, chat included. The shell reads the
 * view from the URL on popstate, so links need no access to its state. */
export function openWorkspaceView(view: string, params: Record<string, string> = {}) {
  const base = "/" + window.location.pathname.split("/").filter(Boolean)[0];
  window.history.pushState({}, "", `${base}?${new URLSearchParams({ view, ...params })}`);
  window.dispatchEvent(new PopStateEvent("popstate"));
}
