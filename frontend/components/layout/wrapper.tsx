"use client";
import copy from "@/components/counselor/workspace/copy.json";
import { useEffect, useState } from "react";
import { useDesktopWorkspaceState } from "./use-desktop-workspace-state";
import { CounselorShell } from "@/components/counselor/workspace/shell";
import { OnboardingView } from "@/components/onboarding/onboarding-view";
import { useWorkspace } from "@/lib/workspace-context";
import { workspaceApi } from "@/lib/api";
import type { OnboardingState } from "@/lib/onboarding";
import { useT } from "@/lib/i18n";
import { Button } from "@/components/ui/button";
function WorkspaceLoadingScreen() {
  const t = useT();

  return (
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-background">
      <div className="flex flex-col items-center gap-5">
        <img
          src="/pai-emblem.png"
          alt="Placement AI"
          className="size-16 animate-[pulse_2s_ease-in-out_infinite] dark:hidden"
        />
        <img
          src="/pai-emblem.png"
          alt="Placement AI"
          className="size-16 animate-[pulse_2s_ease-in-out_infinite] hidden dark:block"
        />
        <div className="text-center">
          <h1 className="text-xl font-semibold tracking-tight">Placement AI</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            {t("nav.workspaceFallback")}
          </p>
        </div>
      </div>
      <div className="absolute bottom-0 left-0 right-0 h-1 bg-muted overflow-hidden">
        <div className="h-full w-1/3 bg-primary rounded-full animate-[loading-bar_1.5s_ease-in-out_infinite]" />
      </div>
      <style>{`
        @keyframes loading-bar {
          0% { transform: translateX(-100%); }
          50% { transform: translateX(150%); }
          100% { transform: translateX(400%); }
        }
      `}</style>
    </div>
  );
}

function OnboardingLoadError({ retry }: { retry: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-4 bg-background p-6 text-center">
      <img src="/pai-emblem.png" alt="Placement AI" className="size-14" />
      <div>
        <h1 className="font-semibold">{copy.onboardingError}</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {copy.onboardingRetry}
        </p>
      </div>
      <Button onClick={retry}>{copy.retry}</Button>
    </div>
  );
}

export function Wrapper() {
  useDesktopWorkspaceState();
  const { loading } = useWorkspace();
  const [onboarding, setOnboarding] = useState<OnboardingState | null>(null);
  const [checked, setChecked] = useState(false),
    [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (loading) return;
    let cancelled = false;
    setChecked(false);
    workspaceApi
      .getOnboarding()
      .then((state) => {
        if (!cancelled) setOnboarding(state);
      })
      .catch(() => {
        if (!cancelled) setOnboarding(null);
      })
      .finally(() => {
        if (!cancelled) setChecked(true);
      });
    return () => {
      cancelled = true;
    };
  }, [loading, attempt]);
  if (loading || !checked) return <WorkspaceLoadingScreen />;
  if (!onboarding)
    return (
      <OnboardingLoadError retry={() => setAttempt((value) => value + 1)} />
    );
  if (onboarding.required)
    return (
      <OnboardingView
        state={onboarding}
        onDone={() => setOnboarding({ ...onboarding, required: false })}
      />
    );
  return <CounselorShell />;
}
