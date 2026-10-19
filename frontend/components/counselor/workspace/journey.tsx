"use client";
import { workspaceApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Heading, LoadState, useResource } from "./resource";
import copy from "./copy.json";
const load = () => workspaceApi.getCounselorWorkspace();
export function Journey({
  navigate,
}: {
  navigate: (view: string, event?: string) => void;
}) {
  const resource = useResource(load);
  return (
    <>
      <Heading title={copy.journeyTitle} description={copy.journeyIntro} />
      {!resource.data || resource.error ? (
        <LoadState
          error={resource.error}
          busy={resource.busy}
          retry={resource.refresh}
        />
      ) : (
        <ol className="mx-auto max-w-3xl">
          {copy.stages.map((stage) => {
            const moment =
              "action" in stage
                ? resource.data?.moments[stage.action!]
                : undefined;
            return (
              <li
                key={stage.id}
                className="relative flex gap-5 pb-7 after:absolute after:bottom-0 after:left-5 after:top-12 after:w-px after:bg-border last:after:hidden"
              >
                <div className="flex size-10 shrink-0 items-center justify-center rounded-full border bg-card text-sm text-primary">
                  {stage.id}
                </div>
                <div className="flex w-full flex-wrap items-center justify-between gap-3 rounded-xl border bg-card p-5">
                  <h2 className="font-semibold">{stage.title}</h2>
                  <Button
                    variant="ghost"
                    onClick={() => navigate(stage.view, moment)}
                  >
                    {moment
                      ? copy.moment
                      : copy.nav[stage.view as keyof typeof copy.nav]}
                  </Button>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </>
  );
}
