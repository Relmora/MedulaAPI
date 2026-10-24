import { ArrowUpRight, CalendarDays, ChevronLeft, ChevronRight, FolderKanban } from "lucide-react";
import { Link } from "react-router";
import { Button } from "@/components/ui/button";
import type { Page } from "@/services/http";
import type { Workspace } from "@/services/workspace";

type WorkspaceListProps = { page: Page<Workspace>; offset: number; onOffsetChange: (offset: number) => void };

export function WorkspaceList({ page, offset, onOffsetChange }: WorkspaceListProps) {
  if (!page.items.length) {
    return (
      <div className="flex min-h-72 flex-col items-center justify-center rounded-2xl border border-dashed border-stone-300 bg-white/60 px-6 text-center">
        <span className="mb-4 rounded-2xl bg-stone-100 p-4 text-stone-500"><FolderKanban className="size-6" aria-hidden="true" /></span>
        <h2 className="text-lg font-normal text-stone-900">{offset ? "No workspaces on this page" : "Create your first workspace"}</h2>
        <p className="mt-2 max-w-sm text-sm leading-6 text-stone-500">Workspaces group related knowledge bases so everything for a project stays together.</p>
      </div>
    );
  }

  return (
    <>
      <div className="overflow-hidden rounded-2xl border border-stone-200 bg-white">
        {page.items.map((workspace) => (
          <Link key={workspace.id} to={`/workspaces/${workspace.id}`} className="group flex items-center gap-4 border-b border-stone-100 px-5 py-4 transition-colors last:border-b-0 hover:bg-stone-50 sm:px-6">
            <span className="rounded-xl bg-teal-50 p-3 text-teal-700">
              <FolderKanban className="size-5" aria-hidden="true" />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="truncate text-base font-normal tracking-[-0.015em] text-stone-950 sm:text-lg">{workspace.name}</h2>
              <p className="mt-1 flex items-center gap-2 text-xs text-stone-400">
                <CalendarDays className="size-3.5" aria-hidden="true" />
                Created {new Date(workspace.created_at).toLocaleDateString()}
              </p>
            </div>
            <ArrowUpRight className="size-4 text-stone-300 transition-all group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:text-teal-700" />
          </Link>
        ))}
      </div>
      {(offset > 0 || offset + page.limit < page.total) && (
        <nav aria-label="Workspace pages" className="mt-8 flex items-center justify-between border-t border-stone-200 pt-6">
          <p className="text-sm text-stone-500">{page.total} workspaces</p>
          <div className="flex gap-2">
            <Button variant="outline" size="icon" aria-label="Previous page" disabled={!offset} onClick={() => onOffsetChange(Math.max(0, offset - page.limit))}><ChevronLeft className="size-4" /></Button>
            <Button variant="outline" size="icon" aria-label="Next page" disabled={offset + page.limit >= page.total} onClick={() => onOffsetChange(offset + page.limit)}><ChevronRight className="size-4" /></Button>
          </div>
        </nav>
      )}
    </>
  );
}
