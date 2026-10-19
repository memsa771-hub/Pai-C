"use client";
import { useEffect, useState } from "react";
import { AnimatePresence, MotionConfig, motion } from "motion/react";
import {
  MessageCircle,
  Route,
  Compass,
  UserRound,
  Columns2,
  ListChecks,
  Files,
  Settings,
  Ellipsis,
  Flag,
  type LucideIcon,
} from "lucide-react";
import { useLayout, type ViewMode } from "@/components/layout/layout-context";
import { useWorkspace } from "@/lib/workspace-context";
import { ChatView } from "@/components/chat/chat-view";
import { FileList } from "@/components/files/file-list";
import { FilePreview } from "@/components/files/file-preview";
import { NotificationsMenu } from "@/components/layout/notifications-menu";
import { UserMenu } from "@/components/layout/user-menu";
import { NotificationsCenterView } from "@/components/notifications/notifications-center-view";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { SidebarProvider } from "@/components/ui/sidebar";
import { StatChip, toneClass, type Tone } from "@/components/pai";
import { cn } from "@/lib/utils";
import { LivingProfile } from "./profile";
import { Journey } from "./journey";
import { Paths, PathPage, ProgramPage } from "./paths";
import { Compare, Plan } from "./decisions";
import { CounselorSettings } from "./settings";
import { DocumentsView } from "./documents";
import { workspaceApi } from "@/lib/api";
import { useResource } from "./resource";
import { useJourney } from "./use-journey";
import copy from "./copy.json";

type NavKey = keyof typeof copy.nav;
const NAV: { key: NavKey; icon: LucideIcon; tone: Tone; group: keyof typeof copy.shell.groups }[] = [
  { key: "threads", icon: MessageCircle, tone: "blue", group: "main" },
  { key: "journey", icon: Route, tone: "violet", group: "main" },
  { key: "paths", icon: Compass, tone: "teal", group: "main" },
  { key: "profile", icon: UserRound, tone: "rose", group: "main" },
  { key: "compare", icon: Columns2, tone: "amber", group: "decide" },
  { key: "plan", icon: ListChecks, tone: "sky", group: "decide" },
  { key: "files", icon: Files, tone: "blue", group: "yours" },
  { key: "settings", icon: Settings, tone: "violet", group: "yours" },
];
/** Phone tab bar: four destinations plus More (bottom-nav limit of five). */
const TABS: NavKey[] = ["threads", "journey", "paths", "profile"];
const health = () => workspaceApi.getCounselorHealth();

function Brand() {
  return (
    <span className="flex items-center gap-3">
      <span className="flex size-10 items-center justify-center rounded-xl bg-white shadow-soft ring-1 ring-border">
        <img src="/pai-emblem.png" alt="" className="size-6 object-contain" />
      </span>
      <span className="text-base font-bold tracking-tight">{copy.brand}</span>
    </span>
  );
}

export function CounselorShell() {
  const { viewMode, openView } = useLayout();
  const { currentSessionId, setCurrentSessionId } = useWorkspace();
  const [draft, setDraft] = useState("");
  const [more, setMore] = useState(false),
    [path, setPath] = useState<string | null>(null),
    [places, setPlaces] = useState(false),
    [base, setBase] = useState("");
  const diagnostic = useResource(health);
  const journey = useJourney();
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
    setMore(false);
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
  const stage = journey.progress?.stage;
  const doneCount = journey.progress?.current ?? 0;
  const navButton = (item: (typeof NAV)[number]) => {
    const Icon = item.icon;
    const current = active === item.key;
    return (
      <button
        key={item.key}
        onClick={() => navigate(item.key)}
        aria-current={current ? "page" : undefined}
        className={cn(
          "group flex min-h-11 w-full items-center gap-3 rounded-xl px-3 text-left text-sm font-medium transition-colors",
          current ? "bg-sidebar-accent text-sidebar-accent-foreground" : "text-foreground/80 hover:bg-muted hover:text-foreground",
        )}
      >
        <span className={cn("flex size-8 items-center justify-center rounded-lg transition-colors",
          current ? cn(toneClass[item.tone].solid) : cn(toneClass[item.tone].soft, toneClass[item.tone].ink))}>
          <Icon aria-hidden className="size-[18px]" />
        </span>
        {copy.nav[item.key]}
      </button>
    );
  };
  const content =
    active === "threads" ? (
      <div className="min-h-0 flex-1">
        <ChatView counselorOnly initialDraft={draft} />
      </div>
    ) : active === "files" ? (
      <DocumentsView list={<FileList />} preview={<FilePreview />} />
    ) : active === "notifications" ? (
      <NotificationsCenterView />
    ) : (
      <div data-scroll-area className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-6xl px-4 pb-16 pt-6 sm:px-8 sm:pt-9">
          {active === "profile" && <LivingProfile onChat={chat} stage={journey.progress?.stage} />}
          {active === "journey" && <Journey navigate={navigate} journey={journey} />}
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
          {active === "settings" && <CounselorSettings base={base} />}
        </div>
      </div>
    );
  return (
    <MotionConfig reducedMotion="user">
    <SidebarProvider>
      <div data-scroll-root className="flex h-svh w-full overflow-hidden bg-background text-foreground">
        <a href="#pai-main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[60] focus:rounded-lg focus:bg-card focus:px-4 focus:py-2 focus:shadow-lift">
          {copy.shell.skip}
        </a>
        <aside className="hidden w-72 shrink-0 flex-col border-r bg-sidebar lg:flex">
          <a href={base || "#"} className="flex shrink-0 items-center px-5 py-5" aria-label={copy.brand}>
            <Brand />
          </a>
          <nav className="min-h-0 flex-1 space-y-5 overflow-y-auto px-3 pb-4" aria-label={copy.brand}>
            {(Object.keys(copy.shell.groups) as (keyof typeof copy.shell.groups)[]).map((group) => (
              <div key={group}>
                <p className="mb-1.5 px-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">{copy.shell.groups[group]}</p>
                <div className="space-y-0.5">{NAV.filter((item) => item.group === group).map(navButton)}</div>
              </div>
            ))}
          </nav>
          {stage && (
            <div className="m-3 rounded-2xl bg-gradient-to-br from-[var(--hero-from)] via-[var(--hero-via)] to-[var(--hero-to)] p-4 text-white">
              <p className="text-xs font-semibold uppercase tracking-wider text-white/85">{copy.shell.stage.replace("{id}", stage.id)}</p>
              <p className="mt-0.5 font-bold">{stage.title}</p>
              <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/25" role="progressbar" aria-valuemin={0}
                aria-valuemax={copy.stages.length} aria-valuenow={doneCount} aria-label={copy.shell.progress.replace("{done}", String(doneCount)).replace("{total}", String(copy.stages.length))}>
                <div className="h-full rounded-full bg-white" style={{ width: `${(doneCount / copy.stages.length) * 100}%` }} />
              </div>
              <p className="mt-1.5 text-xs text-white/85">{copy.shell.progress.replace("{done}", String(doneCount)).replace("{total}", String(copy.stages.length))}</p>
              <button onClick={() => navigate("journey")}
                className="mt-3 min-h-11 w-full rounded-xl bg-white/95 px-3 text-sm font-semibold text-[#1a2a6c] transition-colors hover:bg-white">
                {copy.shell.seeJourney}
              </button>
            </div>
          )}
        </aside>
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-16 shrink-0 items-center justify-between gap-3 border-b bg-background/85 px-4 backdrop-blur sm:px-6 lg:px-8">
            <div className="flex min-w-0 items-center gap-3">
              <span className="lg:hidden"><span className="flex size-10 items-center justify-center rounded-xl bg-white shadow-soft ring-1 ring-border"><img src="/pai-emblem.png" alt={copy.brand} className="size-6 object-contain" /></span></span>
              <p className="truncate text-base font-semibold"><span className="sm:hidden">{copy.shell.short[active as NavKey]}</span><span className="max-sm:hidden">{copy.nav[active as NavKey]}</span></p>
            </div>
            <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
              {stage && (
                <button onClick={() => navigate("journey")} className="rounded-full" aria-label={`${copy.shell.stage.replace("{id}", stage.id)}: ${stage.title}`}>
                  <StatChip tone="blue" icon={Flag} className="min-h-9">
                    <span className="sm:hidden">{stage.id}</span>
                    <span className="hidden sm:inline">{copy.shell.stage.replace("{id}", stage.id)} · {stage.title}</span>
                  </StatChip>
                </button>
              )}
              <NotificationsMenu side="bottom" align="end" />
              <UserMenu side="bottom" align="end" variant="avatar"
                profileAction={{ label: copy.nav.profile, onSelect: () => navigate("profile") }} />
            </div>
          </header>
          {diagnostic.data?.planner_lag_alert && (
            <p role="status" className="shrink-0 border-b bg-warning-soft px-6 py-2 text-xs font-medium text-warning-ink">
              {copy.lag}
            </p>
          )}
          <main id="pai-main" className="flex min-h-0 flex-1 flex-col">
            <AnimatePresence mode="wait" initial={false}>
              <motion.div key={`${active}:${path || ""}:${places}`} className="flex min-h-0 flex-1 flex-col"
                initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}
                transition={{ duration: 0.18, ease: "easeOut" }}>
                {content}
              </motion.div>
            </AnimatePresence>
          </main>
          <nav aria-label={copy.brand} className="grid shrink-0 grid-cols-5 border-t bg-card/95 px-1 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden">
            {TABS.map((key) => {
              const item = NAV.find((n) => n.key === key)!;
              const Icon = item.icon;
              const current = active === key;
              return (
                <button key={key} onClick={() => navigate(key)} aria-current={current ? "page" : undefined}
                  className={cn("flex min-h-16 flex-col items-center justify-center gap-1 text-[11px] font-semibold", current ? "text-brand-ink" : "text-muted-foreground")}>
                  <span className={cn("flex h-7 w-12 items-center justify-center rounded-full transition-colors", current && "bg-brand-soft")}>
                    <Icon aria-hidden className="size-5" />
                  </span>
                  <span className="max-w-full truncate px-0.5">{copy.shell.tabs[key as keyof typeof copy.shell.tabs]}</span>
                </button>
              );
            })}
            <button onClick={() => setMore(true)} aria-haspopup="dialog" aria-expanded={more}
              aria-current={!TABS.includes(active as NavKey) ? "page" : undefined}
              className={cn("flex min-h-16 flex-col items-center justify-center gap-1 text-[11px] font-semibold", !TABS.includes(active as NavKey) ? "text-brand-ink" : "text-muted-foreground")}>
              <span className={cn("flex h-7 w-12 items-center justify-center rounded-full", !TABS.includes(active as NavKey) && "bg-brand-soft")}>
                <Ellipsis aria-hidden className="size-5" />
              </span>
              {copy.shell.more}
            </button>
          </nav>
        </div>
        <Sheet open={more} onOpenChange={setMore}>
          <SheetContent side="bottom" className="rounded-t-3xl pb-[max(1.5rem,env(safe-area-inset-bottom))]">
            <SheetHeader>
              <SheetTitle>{copy.shell.moreTitle}</SheetTitle>
              <SheetDescription className="sr-only">{copy.shell.moreTitle}</SheetDescription>
            </SheetHeader>
            <div className="grid gap-1">{NAV.filter((item) => !TABS.includes(item.key)).map(navButton)}</div>
          </SheetContent>
        </Sheet>
      </div>
    </SidebarProvider>
    </MotionConfig>
  );
}
