"use client";
import { useEffect, useRef } from "react";
import { ArrowLeft, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DOCUMENT_ACCEPT } from "@/lib/document-types";
import { useWorkspace } from "@/lib/workspace-context";
import { useLayout } from "@/components/layout/layout-context";
import { cn } from "@/lib/utils";
import copy from "./copy.json";

/** Documents: the file list and a preview, with one upload action (the same
 * upload queue the file manager uses). On a phone the list comes first and
 * the preview replaces it once a file is chosen. */
export function DocumentsView({ list, preview }: { list: React.ReactNode; preview: React.ReactNode }) {
  const { selectedFileId, setSelectedFileId, enqueueUploads, currentFilePath } = useWorkspace();
  const { mobilePane, openMobileList } = useLayout();
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { openMobileList(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const detail = !!selectedFileId || mobilePane === "detail";
  return (
    <div className="flex min-h-0 flex-1 flex-col px-4 pb-4 pt-5 sm:px-8 sm:pb-6">
      <div className="mx-auto flex w-full max-w-6xl min-h-0 flex-1 flex-col">
        <div className="mb-4 flex shrink-0 items-center justify-between gap-3">
          <h1 className="text-xl font-extrabold tracking-tight sm:text-2xl">{copy.documentsTitle}</h1>
          <input ref={input} type="file" multiple hidden accept={`image/*,${DOCUMENT_ACCEPT}`}
            onChange={(e) => { if (e.target.files?.length) enqueueUploads(Array.from(e.target.files), currentFilePath || ""); e.target.value = ""; }} />
          <Button size="tap" onClick={() => input.current?.click()}><Upload aria-hidden />{copy.documents.upload}</Button>
        </div>
        <div className="flex min-h-[420px] flex-1 overflow-hidden rounded-2xl border bg-card shadow-card">
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
      </div>
    </div>
  );
}
