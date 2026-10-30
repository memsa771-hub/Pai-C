"use client";
/** Pieces of the workspace frame: sections, the sliding nav, the "you are
 * here" card, sub-tabs and the command menu. Copy lives in copy.json. */
import * as React from "react";
import { motion } from "motion/react";
import { CornerDownLeft, FolderLock, LayoutDashboard, Map, MessageCircle, Route, Settings, type LucideIcon } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  Command, CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, CommandShortcut,
} from "@/components/ui/command";
import { cn } from "@/lib/utils";
import { useParams, useRouter } from "next/navigation";
import { OS_PAGES } from "@/components/os/os-nav-group";
import { OS_UI_ENABLED } from "@/lib/config";
import { useT } from "@/lib/i18n";
import copy from "./copy.json";

export type SectionKey = keyof typeof copy.sections;
export type SubView = keyof typeof copy.subTabs;

/** Four places plus Settings. A section owns one or more views; the first is
 * where its nav item lands. */
export const SECTIONS: { key: SectionKey; icon: LucideIcon; views: string[] }[] = [
  { key: "overview", icon: LayoutDashboard, views: ["overview", "mirror"] },
  { key: "threads", icon: MessageCircle, views: ["threads", "notifications"] },
  { key: "roadmaps", icon: Map, views: ["paths", "roadmap"] },
  { key: "journey", icon: Route, views: ["journey"] },
  { key: "vault", icon: FolderLock, views: ["files", "profile"] },
  { key: "settings", icon: Settings, views: ["settings"] },
];
export const MAIN_SECTIONS = SECTIONS.filter((s) => s.key !== "settings");
export const sectionOf = (view: string) => SECTIONS.find((s) => s.views.includes(view)) ?? SECTIONS[0];

/** A sidebar destination on the navy rail: icon and label, a soft lit
 * background and a brand-blue edge when current. Collapsed, the label moves
 * into a tooltip and stays the accessible name. */
export function NavItem({ section, current, collapsed, onSelect }: {
  section: (typeof SECTIONS)[number];
  current: boolean;
  collapsed?: boolean;
  onSelect: () => void;
}) {
  const label = copy.sections[section.key].label;
  const Icon = section.icon;
  const button = (
    <button onClick={onSelect} aria-current={current ? "page" : undefined} aria-label={collapsed ? label : undefined}
      className={cn(
        "group relative flex h-11 w-full items-center gap-3 rounded-full text-sm font-semibold transition-colors duration-200",
        collapsed ? "justify-center" : "px-4",
        current ? "text-primary-foreground" : "text-muted-foreground hover:bg-accent hover:text-foreground",
      )}>
      {current && (
        <motion.span layoutId="nav-pill" aria-hidden className="absolute inset-0 rounded-full bg-primary shadow-[0_8px_18px_-8px_rgb(21_94_239/0.6)]"
          transition={{ type: "spring", stiffness: 500, damping: 40 }} />
      )}
      <Icon aria-hidden className="relative size-[19px] shrink-0" strokeWidth={current ? 2.2 : 1.9} />
      {!collapsed && <span className="relative truncate">{label}</span>}
    </button>
  );
  if (!collapsed) return button;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{button}</TooltipTrigger>
      <TooltipContent side="right">{label}</TooltipContent>
    </Tooltip>
  );
}

export function HerePill({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <span className={cn("inline-flex items-center rounded-full border-[1.5px] border-highlight-ink bg-highlight px-2.5 py-0.5 text-xs font-bold uppercase tracking-wide text-highlight-ink", className)}>
      {children}
    </span>
  );
}

/** Views inside one section: the pill navigation of the PAI dashboard
 * design, a white track with a blue pill that slides to the current view. */
export function SubTabs({ views, current, onSelect, className }: {
  views: string[];
  current: string;
  onSelect: (view: string) => void;
  className?: string;
}) {
  return (
    <div role="group" aria-label={copy.shell.sectionsLabel}
      className={cn("inline-flex items-center gap-1 rounded-full bg-card p-1 shadow-soft ring-1 ring-inset ring-border", className)}>
      {views.map((view) => {
        const on = view === current;
        return (
          <button key={view} onClick={() => onSelect(view)} aria-current={on ? "page" : undefined}
            className={cn("relative min-h-9 flex-1 rounded-full px-4 text-[13px] font-semibold transition-colors sm:flex-none",
              on ? "text-primary-foreground" : "text-foreground/80 hover:text-foreground")}>
            {on && (
              <motion.span layoutId="subtab-pill" aria-hidden className="absolute inset-0 rounded-full bg-primary"
                transition={{ type: "spring", stiffness: 520, damping: 40 }} />
            )}
            <span className="relative">{copy.subTabs[view as SubView]}</span>
          </button>
        );
      })}
    </div>
  );
}

const isMac = () => typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);
export function shortcutLabel() {
  return isMac() ? "⌘K" : "Ctrl K";
}

/** Jump anywhere, or hand a question straight to PAI as a draft. Nothing is
 * sent from here: asking only opens the conversation with the words typed. */
export function CommandMenu({ open, onOpenChange, onGo, onAsk }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onGo: (view: string) => void;
  onAsk: (text: string) => void;
}) {
  const [q, setQ] = React.useState("");
  React.useEffect(() => { if (!open) setQ(""); }, [open]);
  // Merge pai-c + pai-os: PAI OS pages (only when NEXT_PUBLIC_OS_ENABLED=true).
  const router = useRouter();
  const { workspaceId } = useParams<{ workspaceId: string }>() ?? {};
  const t = useT();
  const run = (fn: () => void) => { onOpenChange(false); fn(); };
  const places = SECTIONS.flatMap((section) =>
    section.views.filter((view) => view !== "notifications").map((view) => ({
      view,
      section,
      // "Overview · Mirror", but never "Overview · Overview".
      label: section.views.filter((v) => v !== "notifications").length > 1
        && copy.subTabs[view as SubView] !== copy.sections[section.key].label
        ? `${copy.sections[section.key].label} · ${copy.subTabs[view as SubView]}`
        : copy.sections[section.key].label,
    })));
  return (
    <CommandDialog open={open} onOpenChange={onOpenChange} title={copy.shell.commandTitle} description={copy.shell.commandTitle}
      className="rounded-2xl! border bg-popover shadow-lift max-sm:w-[calc(100%-1.5rem)]">
      {/* Places match only when every word typed is in them; "Ask PAI" always
          matches but ranks below a real place, so a question goes to PAI. */}
      <Command className="bg-transparent"
        filter={(value, search) => {
          if (value.startsWith("ask ")) return 0.5;
          const words = search.toLowerCase().split(/\s+/).filter(Boolean);
          return words.every((word) => value.toLowerCase().includes(word)) ? 1 : 0;
        }}>
      <CommandInput value={q} onValueChange={setQ} placeholder={copy.shell.commandPlaceholder} />
      <CommandList className="max-h-[min(420px,60svh)]">
        <CommandEmpty>{copy.shell.commandEmpty}</CommandEmpty>
        <CommandGroup heading={copy.shell.commandGo}>
          {places.map(({ view, section, label }) => {
            const Icon = section.icon;
            return (
              <CommandItem key={view} value={`${label} ${copy.sections[section.key].hint}`} onSelect={() => run(() => onGo(view))}>
                <Icon aria-hidden />
                <span>{label}</span>
              </CommandItem>
            );
          })}
        </CommandGroup>
        {OS_UI_ENABLED && workspaceId && (
          <CommandGroup heading={t("nav.studyAbroadPlan")}>
            {OS_PAGES.map(([page, key]) => (
              <CommandItem key={page} value={`${t("nav.studyAbroadPlan")} ${t(key)}`}
                onSelect={() => run(() => router.push(`/${workspaceId}/${page}`))}>
                <span>{t(key)}</span>
              </CommandItem>
            ))}
          </CommandGroup>
        )}
        {q.trim() && (
          <CommandGroup heading={copy.shell.commandAskGroup}>
            <CommandItem value={`ask ${q}`} onSelect={() => run(() => onAsk(q.trim()))}>
              <img src="/pai-emblem.png" alt="" className="size-4 object-contain" />
              <span className="truncate">{copy.shell.commandAsk.replace("{q}", q.trim())}</span>
              <CommandShortcut><CornerDownLeft className="size-3.5" /></CommandShortcut>
            </CommandItem>
          </CommandGroup>
        )}
      </CommandList>
      </Command>
    </CommandDialog>
  );
}
