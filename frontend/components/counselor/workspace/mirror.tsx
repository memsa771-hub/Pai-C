"use client";
/** The Mirror page: "you are this" (FOUR_FEATURES_SPEC 2.6). The backend draws
 * the card from the Vault on every read, so there is nothing to confirm here:
 * the student reads it, says what is wrong (that opens the Vault entry), and
 * tells PAI what is still unknown (that opens the chat with the topic). */
import { workspaceApi } from "@/lib/api";
import { updatedAt } from "@/lib/mirror";
import { LoadState, shortDate, useResource } from "./resource";
import { AreaTile, MirrorHero, NotReady, Unknowns, openEntryInVault, topicOf } from "./mirror-parts";
import copy from "./copy.json";

const t = copy.mirror;
const load = () => workspaceApi.getMirror();

export function Mirror({ onChat, onOpenEntry = openEntryInVault }: {
  onChat: (topic?: string) => void;
  /** "This is wrong" on an entry: opens it in the Vault. */
  onOpenEntry?: (ref: string) => void;
}) {
  const resource = useResource(load);
  const card = resource.data;
  if (!card || resource.error) return <LoadState error={resource.error} busy={resource.busy} retry={resource.refresh} skeleton="profile" />;
  // An area is a tile once PAI knows something there; the rest wait in "Still unknown".
  const areas = card.areas.filter((area) => area.level > 0 || area.entries.length > 0);
  const tell = (unknown: Parameters<typeof topicOf>[0]) => onChat(topicOf(unknown));
  return (
    <div className="space-y-6">
      <MirrorHero card={card} updated={shortDate(updatedAt(card))} />
      {!card.ready && card.unknowns[0] && <NotReady unknown={card.unknowns[0]} onTell={tell} />}
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        {areas.length > 0 && (
          <section aria-labelledby="mirror-areas" className="min-w-0">
            <h2 id="mirror-areas" className="mb-3 font-display text-lg leading-tight">{t.areasTitle}</h2>
            <div className="grid gap-4 sm:grid-cols-2">
              {areas.map((area) => <AreaTile key={area.key} area={area} onWrong={onOpenEntry} />)}
            </div>
          </section>
        )}
        <Unknowns unknowns={card.unknowns} onTell={tell} />
      </div>
    </div>
  );
}
