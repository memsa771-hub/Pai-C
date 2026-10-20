"use client";
import { useEffect, useRef } from "react";
import { ArrowLeft, ArrowRight, FolderOpen, ShieldCheck, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EvidenceBadge, PageHeader } from "@/components/pai";
import { DOCUMENT_ACCEPT } from "@/lib/document-types";
import { useWorkspace } from "@/lib/workspace-context";
import { useLayout } from "@/components/layout/layout-context";
import { cn } from "@/lib/utils";
import copy from "./copy.json";

/** Documents: why to upload, a clear upload action (the same upload queue
 * the file manager uses), then the file list and a preview. On a phone the
 * list comes first and the preview replaces it once a file is chosen. */
export function DocumentsView({ list, preview }: { list: React.ReactNode; preview: React.ReactNode }) {
  const { selectedFileId, setSelectedFileId, enqueueUploads, currentFilePath } = useWorkspace();
  const { mobilePane, openMobileList } = useLayout();
  const input = useRef<HTMLInputElement>(null);
  // Phone: the list first; opening a folder or file (FileList calls
  // openMobileDetail) shows the files, with a way back.
  useEffect(() => { openMobileList(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const detail = !!selectedFileId || mobilePane === "detail";
  return (
    <div data-scroll-area className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <div className="mx-auto flex w-full max-w-6xl min-h-0 flex-1 flex-col px-4 pb-6 pt-6 sm:px-8 sm:pt-9">
        <PageHeader title={copy.documentsTitle} description={copy.documentHelp} icon={FolderOpen} tone="blue"
          action={<>
            <input ref={input} type="file" multiple hidden accept={`image/*,${DOCUMENT_ACCEPT}`}
              onChange={(e) => { if (e.target.files?.length) enqueueUploads(Array.from(e.target.files), currentFilePath || ""); e.target.value = ""; }} />
            <Button size="tap" onClick={() => input.current?.click()}><Upload aria-hidden />{copy.documents.upload}</Button>
          </>} />
        <section className="mb-5 flex flex-wrap items-center gap-4 rounded-3xl bg-gradient-to-br from-tone-blue-soft to-tone-teal-soft p-5">
          <div className="min-w-0 flex-1 basis-72">
            <h2 className="font-bold">{copy.documents.whyTitle}</h2>
            <p className="mt-1 text-sm text-muted-foreground">{copy.documents.whyBody}</p>
            <ul className="mt-3 flex flex-wrap gap-2">
              {copy.documents.examples.map((example) => <li key={example} className="rounded-full bg-card/80 px-3 py-1 text-xs font-semibold">{example}</li>)}
            </ul>
          </div>
          <div aria-hidden className="flex items-center gap-2 rounded-2xl bg-card/80 px-4 py-3">
            <EvidenceBadge level="stated" /><ArrowRight className="size-4 text-muted-foreground" /><EvidenceBadge level="shown" />
          </div>
        </section>
        <div className="flex min-h-[420px] flex-1 overflow-hidden rounded-3xl border bg-card shadow-card">
          <div className={cn("w-full shrink-0 sm:w-72 sm:border-r", detail && "hidden sm:block")}>{list}</div>
          <div className={cn("flex min-w-0 flex-1 flex-col", !detail && "hidden sm:flex")}>
            <div className="border-b p-2 sm:hidden">
              <Button size="tap" variant="ghost" onClick={() => { setSelectedFileId(null); openMobileList(); }}>
                <ArrowLeft aria-hidden />{copy.documents.backToFolders}
              </Button>
            </div>
            <div className="min-h-0 flex-1">{preview}</div>
          </div>
        </div>
        <p className="mt-4 flex items-start gap-2 text-xs text-muted-foreground"><ShieldCheck aria-hidden className="mt-0.5 size-4 shrink-0 text-success" />{copy.documents.privacy}</p>
      </div>
    </div>
  );
}
