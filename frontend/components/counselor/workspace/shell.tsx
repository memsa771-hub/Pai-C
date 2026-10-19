"use client";
import { useEffect, useState } from "react";
import {
  MessageCircle,
  Route,
  Compass,
  UserRound,
  Columns2,
  ListChecks,
  Files,
  Settings,
  Menu,
  X,
} from "lucide-react";
import { useLayout, type ViewMode } from "@/components/layout/layout-context";
import { useWorkspace } from "@/lib/workspace-context";
import { ChatView } from "@/components/chat/chat-view";
import { FileList } from "@/components/files/file-list";
import { FilePreview } from "@/components/files/file-preview";
import { NotificationsMenu } from "@/components/layout/notifications-menu";
import { UserMenu } from "@/components/layout/user-menu";
import { NotificationsCenterView } from "@/components/notifications/notifications-center-view";
import { Button } from "@/components/ui/button";
import { SidebarProvider } from "@/components/ui/sidebar";
import { LivingProfile } from "./profile";
import { Journey } from "./journey";
import { Paths, PathPage, ProgramPage } from "./paths";
import { Compare, Plan } from "./decisions";
import { CounselorSettings } from "./settings";
import { workspaceApi } from "@/lib/api";
import { useResource } from "./resource";
import copy from "./copy.json";
const icons = {
  threads: MessageCircle,
  journey: Route,
  paths: Compass,
  profile: UserRound,
  compare: Columns2,
  plan: ListChecks,
  files: Files,
  settings: Settings,
};
const health = () => workspaceApi.getCounselorHealth();
export function CounselorShell() {
  const { viewMode, openView } = useLayout();
  const { workspace, currentSessionId, setCurrentSessionId } = useWorkspace();
  const [draft, setDraft] = useState("");
  const [mobile, setMobile] = useState(false),
    [path, setPath] = useState<string | null>(null),
    [places, setPlaces] = useState(false),
    [base, setBase] = useState("");
  const diagnostic = useResource(health);
  useEffect(() => {
    if (currentSessionId !== "pai-counselor")
      setCurrentSessionId("pai-counselor");
  }, [currentSessionId, setCurrentSessionId]);
  useEffect(() => {
    setBase("/" + window.location.pathname.split("/").filter(Boolean)[0]);
    const read = () => {
      const q = new URLSearchParams(window.location.search);
      setPath(q.get("path"));
      setPlaces(q.get("stage") === "H");
      const requested = q.get("view") || "threads";
      openView(
        Object.hasOwn(copy.nav, requested)
          ? (requested as ViewMode)
          : "threads",
      );
    };
    read();
    window.addEventListener("popstate", read);
    return () => window.removeEventListener("popstate", read);
  }, []); // URL restored only on navigation, not each render.
  const navigate = (view: string, event?: string) => {
    openView(view as ViewMode);
    setMobile(false);
    setPath(null);
    setPlaces(false);
    const q = new URLSearchParams({ view });
    if (event) q.set("moment", event);
    window.history.pushState({}, "", `${base}?${q}`);
  };
  const openPath = (id: string) => {
    openView("paths");
    setPath(id);
    setPlaces(false);
    window.history.pushState(
      {},
      "",
      `${base}?view=paths&path=${encodeURIComponent(id)}`,
    );
  };
  const chat = (topic?: string) => {
    navigate("threads");
    setDraft(topic || "");
  };
  const active =
    viewMode === "roadmaps"
      ? "compare"
      : Object.hasOwn(copy.nav, viewMode)
        ? viewMode
        : "threads";
  return (
    <SidebarProvider>
      <div className="flex h-svh w-full overflow-hidden bg-background text-foreground">
        {mobile && (
          <button
            className="fixed inset-0 z-40 bg-black/40 md:hidden"
            aria-label={copy.cancel}
            onClick={() => setMobile(false)}
          />
        )}
        <aside
          className={`${mobile ? "translate-x-0" : "-translate-x-full"} fixed inset-y-0 left-0 z-50 flex w-64 flex-col border-r bg-background text-sidebar-foreground transition-transform md:static md:translate-x-0 md:bg-sidebar`}
        >
          <a href={base || "#"} className="flex shrink-0 items-center gap-3 px-4 py-5">
            <img src="/pai-emblem.png" alt="" className="size-9" />
            <div>
              <p className="font-semibold tracking-tight">{workspace?.name || copy.brand}</p>
            </div>
          </a>
          <nav className="min-h-0 flex-1 space-y-1 overflow-y-auto px-2" aria-label={copy.brand}>
            {Object.entries(icons).map(([key, Icon]) => (
              <button
                key={key}
                onClick={() => navigate(key)}
                aria-current={active === key ? "page" : undefined}
                className={`flex min-h-11 w-full items-center gap-3 rounded-md px-3 text-left text-sm transition-colors ${active === key ? "bg-sidebar-accent font-semibold text-sidebar-accent-foreground" : "hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"} ${key === "files" ? "mt-5" : ""}`}
              >
                <Icon className="size-[18px]" />
                {copy.nav[key as keyof typeof copy.nav]}
              </button>
            ))}
          </nav>
          <footer className="mx-3 mt-3 flex shrink-0 items-center gap-2 border-t py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
            <UserMenu side="top" align="start" showIdentity
              profileAction={{label: copy.nav.profile, onSelect: () => navigate("profile")}} />
            <NotificationsMenu side="top" align="end" />
          </footer>
        </aside>
        <main className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-16 shrink-0 items-center justify-between border-b px-4 sm:px-8">
            <div className="flex items-center gap-3">
              <Button
                variant="ghost"
                className="md:hidden"
                aria-label={copy.brand}
                onClick={() => setMobile(!mobile)}
              >
                {mobile ? <X /> : <Menu />}
              </Button>
              <span className="text-sm font-medium">
                {copy.nav[active as keyof typeof copy.nav]}
              </span>
            </div>
            <div className="flex items-center gap-3">
              <span className="hidden items-center gap-2 text-xs text-muted-foreground sm:flex">
                <span
                  className={`size-1.5 rounded-full ${diagnostic.data?.planner_lag_alert ? "bg-amber-500" : "bg-primary"}`}
                />
                {diagnostic.data?.planner_lag_alert
                  ? copy.loading
                  : copy.healthy}
              </span>
            </div>
          </header>
          {diagnostic.data?.planner_lag_alert && (
            <p role="status" className="border-b bg-muted px-6 py-2 text-xs">
              {copy.lag}
            </p>
          )}
          {active === "threads" ? (
            <div className="min-h-0 flex-1">
              <ChatView counselorOnly initialDraft={draft} />
            </div>
          ) : active === "files" ? (
            <div className="flex min-h-0 flex-1">
              <div className="hidden w-56 shrink-0 border-r sm:block">
                <FileList />
              </div>
              <div className="min-w-0 flex-1">
                <FilePreview />
              </div>
            </div>
          ) : active === "notifications" ? (
            <NotificationsCenterView />
          ) : (
            <div className="min-h-0 flex-1 overflow-y-auto">
              <div className="mx-auto max-w-6xl p-5 pb-16 sm:p-9">
                {active === "profile" && <LivingProfile onChat={chat} />}
                {active === "journey" && <Journey navigate={navigate} />}
                {active === "paths" &&
                  (path ? (
                    places ? (
                      <ProgramPage
                        id={path}
                        onBack={() => setPlaces(false)}
                        onCompare={() => navigate("compare")}
                      />
                    ) : (
                      <PathPage
                        id={path}
                        onBack={() => navigate("paths")}
                        onPlaces={() => {
                          setPlaces(true);
                          window.history.pushState(
                            {},
                            "",
                            `${base}?view=paths&path=${encodeURIComponent(path)}&stage=H`,
                          );
                        }}
                        onChat={chat}
                      />
                    )
                  ) : (
                    <Paths onOpen={openPath} />
                  ))}
                {active === "compare" && (
                  <Compare onChat={chat} onOpen={openPath} />
                )}
                {active === "plan" && <Plan onChat={chat} />}
                {active === "settings" && <CounselorSettings base={base} />}
              </div>
            </div>
          )}
        </main>
      </div>
    </SidebarProvider>
  );
}
