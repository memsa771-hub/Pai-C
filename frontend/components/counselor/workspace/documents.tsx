"use client";
import { FolderOpen } from "lucide-react";
import { PageHeader } from "@/components/pai";
import { useWorkspace } from "@/lib/workspace-context";
import { cn } from "@/lib/utils";
import copy from "./copy.json";

/** Documents: the file list and a preview. On a phone the list comes first
 * and the preview replaces it once a file is chosen. */
export function DocumentsView({ list, preview }: { list: React.ReactNode; preview: React.ReactNode }) {
  const { selectedFileId } = useWorkspace();
  return (
    <div data-scroll-area className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <div className="mx-auto flex w-full max-w-6xl min-h-0 flex-1 flex-col px-4 pb-6 pt-6 sm:px-8 sm:pt-9">
        <PageHeader title={copy.documentsTitle} description={copy.documentHelp} icon={FolderOpen} tone="blue" />
        <div className="flex min-h-[420px] flex-1 overflow-hidden rounded-2xl border bg-card shadow-card">
          <div className={cn("w-full shrink-0 border-r sm:w-72", selectedFileId && "hidden sm:block")}>{list}</div>
          <div className={cn("min-w-0 flex-1", !selectedFileId && "hidden sm:block")}>{preview}</div>
        </div>
      </div>
    </div>
  );
}
