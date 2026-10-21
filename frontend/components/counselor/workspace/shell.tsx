"use client";
import { useEffect, useState } from "react";
import { AnimatePresence, LayoutGroup, MotionConfig, motion } from "motion/react";
import { PanelLeftClose, PanelLeftOpen, Search, Settings } from "lucide-react";
import { useLayout, type ViewMode } from "@/components/layout/layout-context";
import { useWorkspace } from "@/lib/workspace-context";
import { ChatView } from "@/components/chat/chat-view";
import { FileList } from "@/components/files/file-list";
import { FilePreview } from "@/components/files/file-preview";
import { NotificationsMenu } from "@/components/layout/notifications-menu";
import { UserMenu } from "@/components/layout/user-menu";
import { NotificationsCenterView } from "@/components/notifications/notifications-center-view";
import { SidebarProvider } from "@/components/ui/sidebar";
import { cn } from "@/lib/utils";
import { LivingProfile } from "./profile";
import { Journey } from "./journey";
import { Paths, PathPage, ProgramPage } from "./paths";
import { Compare, Plan } from "./decisions";
import { CounselorSettings } from "./settings";
import { DocumentsView } from "./documents";
import { Overview } from "./overview";
import { workspaceApi } from "@/lib/api";
import { useResource } from "./resource";
import { useJourney } from "./use-journey";
import {
  CommandMenu, MAIN_SECTIONS, NavItem, SECTIONS, SubTabs, sectionOf, shortcutLabel,
} from "./shell-parts";
import copy from "./copy.json";

const health = () => workspaceApi.getCounselorHealth();
/** Section names in a URL land on the section's first view. */
const ALIASES: Record<string, string> = { roadmaps: "paths", vault: "files", pai: "threads", home: "overview" };
const COLLAPSE_KEY = "pai.sidebar.collapsed";

export function CounselorShell() {
  const { viewMode, openView } = useLayout();
  const { currentSessionId, setCurrentSessionId } = useWorkspace();
  const [draft, setDraft] = useState("");
  const [path, setPath] = useState<string | null>(null),
    [places, setPlaces] = useState(false),
    [base, setBase] = useState(""),
    [collapsed, setCollapsed] = useState(false),
    [command, setCommand] = useState(false);
  const diagnostic = useResource(health);
  const journey = useJourney();
  useEffect(() => {
    if (currentSessionId !== "pai-counselor")
      setCurrentSessionId("pai-counselor");
  }, [currentSessionId, setCurrentSessionId]);
  useEffect(() => {
    setBase("/" + window.location.pathname.split("/").filter(Boolean)[0]);
    try { setCollapsed(localStorage.getItem(COLLAPSE_KEY) === "1"); } catch { /* storage blocked */ }
    const read = () => {
      const q = new URLSearchParams(window.location.search);
      setPath(q.get("path"));
      setPlaces(q.get("stage") === "H");
      const raw = q.get("view") || "threads";
      const requested = ALIASES[raw] || raw;
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
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommand((open) => !open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const toggleSidebar = () => setCollapsed((value) => {
    try { localStorage.setItem(COLLAPSE_KEY, value ? "0" : "1"); } catch { /* storage blocked */ }
    return !value;
  });
  const navigate = (view: string, event?: string) => {
    openView(view as ViewMode);
    // A chat topic is one-shot; chat() sets it again right after navigating.
    setDraft("");
    // Moments, paths and choices change as the student works; keep the stage fresh.
    void journey.refresh();
    setPath(null);
    setPlaces(false);
    const q = new URLSearchParams({ view });
    if (event) q.set("moment", event);
    window.history.pushState({}, "", `${base}?${q}`);
  };
  const openPath = (id: string) => {
    void journey.refresh();
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
  const section = sectionOf(active);
  const subViews = section.views.filter((view) => view in copy.subTabs);
  const content =
    active === "threads" ? (
      <div className="min-h-0 flex-1">
        <ChatView counselorOnly initialDraft={draft} />
      </div>
    ) : active === "files" ? (
      <DocumentsView list={<FileList />} preview={<FilePreview />} />
    ) : active === "overview" ? (
      // Overview is one screen when the window is big enough (fit): cards
      // scroll inside. Smaller windows scroll the page, so nothing is cut off.
      <div data-scroll-area className="relative min-h-0 flex-1 overflow-y-auto fit:overflow-hidden">
        <div className="mx-auto w-full max-w-6xl px-4 pb-6 pt-2 sm:px-8 fit:h-full">
          <Overview journey={journey} navigate={navigate} openPath={openPath} onChat={chat} />
        </div>
      </div>
    ) : active === "notifications" ? (
      <NotificationsCenterView />
    ) : (
      <div data-scroll-area className="relative min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-6xl px-4 pb-16 pt-6 sm:px-8 sm:pt-8">
          {active === "profile" && <LivingProfile onChat={chat} onNavigate={navigate} stage={journey.progress?.stage} />}
          {active === "journey" && <Journey navigate={navigate} journey={journey} onChat={chat} />}
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
              <Paths onOpen={openPath} onChat={chat} />
            ))}
          {active === "compare" && (
            <Compare onChat={chat} onOpen={openPath} />
          )}
          {active === "plan" && <Plan onChat={chat} onNavigate={navigate} />}
          {active === "settings" && <CounselorSettings base={base} onNavigate={navigate} />}
        </div>
      </div>
    );
  const stage = journey.progress?.stage;
  const done = journey.progress?.current ?? 0;
  const total = copy.stages.length;
  const stageLabel = stage ? `${copy.shell.stage.replace("{id}", stage.id)}: ${stage.title}` : "";
  return (
    <MotionConfig reducedMotion="user">
    <SidebarProvider>
      {/* relative + clip: absolutely positioned bits (screen-reader text, rings) stay
          inside the app, so the page itself never grows taller than the window
          and the rail never scrolls away. */}
      <div data-scroll-root className="relative flex h-svh w-full overflow-clip bg-background text-foreground">
        <a href="#pai-main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[60] focus:rounded-lg focus:bg-card focus:px-4 focus:py-2 focus:shadow-lift">
          {copy.shell.skip}
        </a>

        {/* The navy rail: brand, search, four places, the stage, settings and you. */}
        <aside className={cn("relative z-10 my-3 ms-3 hidden shrink-0 flex-col rounded-[22px] border bg-card py-4 shadow-card transition-[width] duration-300 ease-out lg:flex",
          collapsed ? "w-[76px] px-3" : "w-[248px] px-3")}>
          <div className={cn("flex items-center pb-5", collapsed ? "flex-col gap-3" : "justify-between ps-1.5")}>
            <a href={base || "#"} className="flex min-w-0 items-center gap-2.5" aria-label={copy.brand}>
              <img src="/pai-emblem.png" alt="" className="size-8 shrink-0 object-contain" />
              {!collapsed && <span className="min-w-0">
                <span className="block truncate font-display text-[17px] leading-5 text-foreground">{copy.brand}</span>
                <span className="block text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">{copy.shell.forStudents}</span>
              </span>}
            </a>
            <button onClick={toggleSidebar} aria-label={collapsed ? copy.shell.expand : copy.shell.collapse} aria-expanded={!collapsed}
              className="flex size-9 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
              {collapsed ? <PanelLeftOpen aria-hidden className="size-[18px]" /> : <PanelLeftClose aria-hidden className="size-[18px]" />}
            </button>
          </div>
          <button onClick={() => setCommand(true)} aria-label={copy.shell.search} aria-keyshortcuts="Control+K Meta+K"
            title={`${copy.shell.search} (${shortcutLabel()})`}
            className={cn("mb-4 flex h-10 items-center gap-2.5 rounded-full bg-background text-[13px] text-muted-foreground ring-1 ring-inset ring-border transition-colors hover:text-foreground",
              collapsed ? "justify-center" : "px-3.5")}>
            <Search aria-hidden className="size-4 shrink-0" />
            {!collapsed && <>
              <span className="flex-1 truncate text-left">{copy.shell.search}</span>
              <kbd className="rounded-full bg-card px-2 py-0.5 font-sans text-[10px] font-semibold ring-1 ring-border">{shortcutLabel()}</kbd>
            </>}
          </button>
          <LayoutGroup id="sidebar">
            <nav className="min-h-0 flex-1 space-y-1 overflow-y-auto overflow-x-hidden" aria-label={copy.brand}>
              {MAIN_SECTIONS.map((item) => (
                <NavItem key={item.key} section={item} current={section.key === item.key} collapsed={collapsed}
                  onSelect={() => navigate(item.views[0])} />
              ))}
            </nav>
            <div className="space-y-1 pt-3">
              {stage && (collapsed ? (
                <button onClick={() => navigate("journey")} aria-label={stageLabel} title={stageLabel}
                  className="mx-auto mb-1 flex size-11 items-center justify-center rounded-full text-xs font-bold text-primary hover:bg-accent">
                  <span className="flex size-9 items-center justify-center rounded-full bg-brand-soft">{stage.id}</span>
                </button>
              ) : (
                <button onClick={() => navigate("journey")} aria-label={`${stageLabel}. ${copy.shell.progress.replace("{done}", String(done)).replace("{total}", String(total))}`}
                  className="mb-2 w-full rounded-2xl bg-brand-soft px-3.5 py-3 text-left transition-colors hover:bg-brand-soft/70">
                  <span className="flex items-center justify-between text-[11px] font-semibold text-primary">
                    <span>{copy.shell.stage.replace("{id}", stage.id)}</span><span className="tabular-nums">{done}/{total}</span>
                  </span>
                  <span className="mt-0.5 block truncate text-sm font-bold text-foreground">{stage.title}</span>
                  <span aria-hidden className="mt-2 block h-1.5 overflow-hidden rounded-full bg-card">
                    <span className="block h-full rounded-full bg-primary transition-[width] duration-500" style={{ width: `${(done / total) * 100}%` }} />
                  </span>
                </button>
              ))}
              <NavItem section={SECTIONS.find((s) => s.key === "settings")!} current={section.key === "settings"}
                collapsed={collapsed} onSelect={() => navigate("settings")} />
              <div className={cn("flex pt-1", collapsed && "justify-center")}>
                <UserMenu side="right" align="end" showIdentity={!collapsed} variant={collapsed ? "avatar" : "default"} />
              </div>
            </div>
          </LayoutGroup>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-16 shrink-0 items-center gap-3 px-4 sm:px-6 lg:px-8">
            <span className="flex size-8 items-center justify-center rounded-lg bg-white ring-1 ring-border lg:hidden">
              <img src="/pai-emblem.png" alt={copy.brand} className="size-5 object-contain" />
            </span>
            {subViews.length > 1 && (
              <SubTabs views={subViews} current={active} onSelect={navigate} className="max-md:hidden" />
            )}
            <div className="ms-auto flex items-center gap-1">
              <button onClick={() => setCommand(true)} aria-label={copy.shell.search}
                className="flex size-10 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground lg:hidden">
                <Search aria-hidden className="size-[18px]" />
              </button>
              <NotificationsMenu side="bottom" align="end" />
              {/* Phones have no sidebar: the same single Settings page, one tap away. */}
              <button onClick={() => navigate("settings")} aria-label={copy.sections.settings.label} aria-current={section.key === "settings" ? "page" : undefined}
                className={cn("flex size-10 items-center justify-center rounded-full hover:bg-muted lg:hidden",
                  section.key === "settings" ? "bg-brand-soft text-primary" : "text-muted-foreground hover:text-foreground")}>
                <Settings aria-hidden className="size-[18px]" />
              </button>
              <span className="lg:hidden"><UserMenu side="bottom" align="end" variant="avatar" /></span>
            </div>
          </header>
          {subViews.length > 1 && (
            <div className="shrink-0 px-4 pb-2 md:hidden">
              <SubTabs views={subViews} current={active} onSelect={navigate} className="flex w-full" />
            </div>
          )}
          {diagnostic.data?.planner_lag_alert && (
            <p role="status" className="shrink-0 border-b bg-warning-soft px-6 py-2 text-xs font-medium text-warning-ink">
              {copy.lag}
            </p>
          )}
          <main id="pai-main" className="flex min-h-0 flex-1 flex-col">
            <AnimatePresence mode="wait" initial={false}>
              <motion.div key={`${active}:${path || ""}:${places}`} className="flex min-h-0 flex-1 flex-col"
                initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}
                transition={{ duration: 0.16, ease: "easeOut" }}>
                {content}
              </motion.div>
            </AnimatePresence>
          </main>

        <LayoutGroup id="tabs">
          <nav aria-label={copy.brand} className="grid shrink-0 grid-cols-5 border-t bg-card px-2 pb-[env(safe-area-inset-bottom)] lg:hidden">
            {MAIN_SECTIONS.map((item) => {
              const current = section.key === item.key;
              const Icon = item.icon;
              return (
                <button key={item.key} onClick={() => navigate(item.views[0])} aria-current={current ? "page" : undefined}
                  className={cn("relative flex min-h-16 flex-col items-center justify-center gap-1 text-[11px] font-semibold transition-colors",
                    current ? "text-primary" : "text-muted-foreground")}>
                  {current && <motion.span layoutId="tab-indicator" aria-hidden className="absolute inset-x-6 top-0 h-[3px] rounded-b-full bg-primary" />}
                  <Icon aria-hidden className="size-[22px]" strokeWidth={current ? 2.25 : 1.9} />
                  {copy.sections[item.key].label}
                </button>
              );
            })}
          </nav>
        </LayoutGroup>
        </div>
        <CommandMenu open={command} onOpenChange={setCommand} onGo={navigate} onAsk={chat} />
      </div>
    </SidebarProvider>
    </MotionConfig>
  );
}
