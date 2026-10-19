"use client";
import { workspaceApi } from "@/lib/api";
import { RoadmapsView } from "@/components/roadmaps/roadmaps-view";
import { Button } from "@/components/ui/button";
import { Heading, LoadState, useResource } from "./resource";
import copy from "./copy.json";
const load = () => workspaceApi.getPossibilities();
export function Compare({
  onChat,
  onOpen,
}: {
  onChat: (text: string) => void;
  onOpen: (id: string) => void;
}) {
  const resource = useResource(load);
  return (
    <>
      <Heading title={copy.compare} description={copy.chooseHelp} />
      {!resource.data || resource.error ? (
        <LoadState
          error={resource.error}
          busy={resource.busy}
          retry={resource.refresh}
        />
      ) : (
        <div className="overflow-x-auto rounded-2xl border bg-card">
          <table className="w-full min-w-[500px] text-left text-sm">
            <thead className="bg-muted/50">
              <tr>
                <th className="p-4">{copy.nav.paths}</th>
                <th className="p-4">{copy.why}</th>
                <th className="p-4">{copy.source}</th>
              </tr>
            </thead>
            <tbody>
              {resource.data
                .filter((p) => p.status !== "dismissed")
                .map((path) => (
                  <tr key={path.id} className="border-t">
                    <td className="p-4">
                      <Button variant="ghost" onClick={() => onOpen(path.id)}>
                        {path.title}
                      </Button>
                    </td>
                    <td className="p-4 leading-relaxed">{path.why}</td>
                    <td className="p-4 text-muted-foreground">
                      {path.evidence.map((e) => e.text).join(" · ")}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}
      <Button
        variant="outline"
        className="my-6"
        onClick={() => onChat(copy.family)}
      >
        {copy.family}
      </Button>
      <p className="mb-6 text-sm text-muted-foreground">
        {copy.decisionPending}
      </p>
      <section className="min-h-[400px] rounded-2xl border bg-card">
        <RoadmapsView pathOnly />
      </section>
    </>
  );
}
export function Plan({ onChat }: { onChat: (text: string) => void }) {
  return (
    <>
      <Heading title={copy.planTitle} description={copy.planIntro} />
      <section className="mb-6 rounded-2xl border border-primary/20 bg-primary/5 p-6">
        <h2 className="text-xl font-semibold">{copy.checkin}</h2>
        <p className="my-3 text-muted-foreground">{copy.checkinHelp}</p>
        <Button onClick={() => onChat(copy.checkin)}>{copy.moment}</Button>
      </section>
      <section className="min-h-[500px] rounded-2xl border bg-card">
        <RoadmapsView pathOnly />
      </section>
    </>
  );
}
