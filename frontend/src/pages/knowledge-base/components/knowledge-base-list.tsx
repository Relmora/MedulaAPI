import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowUpRight,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  Plus,
} from "lucide-react";
import { Link, useNavigate } from "react-router";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { getErrorMessage } from "@/services/http";
import { getKnowledgeBases } from "@/services/knowledge-base";
import { KnowledgeBaseForm } from "./knowledge-base-form";

export function KnowledgeBaseList({ workspaceId }: { workspaceId: string }) {
  const [offset, setOffset] = useState(0);
  const [creating, setCreating] = useState(false);
  const navigate = useNavigate();
  const query = useQuery({
    queryKey: ["knowledge-bases", workspaceId, offset],
    queryFn: ({ signal }) => getKnowledgeBases(workspaceId, offset, signal),
  });

  return (
    <section className="pt-8">
      <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
        <div>
          <h2 className="text-2xl font-normal tracking-[-0.025em] text-stone-950">
            Knowledge bases
          </h2>
          <p className="mt-1 text-sm leading-6 text-stone-500">
            Keep related documents and context together.
            {query.data && ` ${query.data.total} total.`}
          </p>
        </div>
        <Button
          onClick={() => setCreating(true)}
          className="h-10 rounded-xl bg-stone-950 px-4 font-normal text-white hover:bg-teal-700"
        >
          <Plus className="size-4" />
          New knowledge base
        </Button>
      </div>

      <div className="mt-6">
        {query.isPending ? (
          <div className="space-y-3">
            {[0, 1, 2].map((item) => (
              <Skeleton key={item} className="h-20 rounded-xl" />
            ))}
          </div>
        ) : query.isError ? (
          <Alert variant="destructive">
            <AlertDescription className="flex items-center justify-between gap-4">
              <span>{getErrorMessage(query.error)}</span>
              <Button variant="outline" onClick={() => void query.refetch()}>
                Try again
              </Button>
            </AlertDescription>
          </Alert>
        ) : !query.data.items.length ? (
          <div className="flex min-h-64 flex-col items-center justify-center rounded-2xl border border-dashed border-stone-300 bg-white/60 px-6 text-center">
            <span className="mb-4 rounded-2xl bg-teal-50 p-4 text-teal-700">
              <BookOpen className="size-6" aria-hidden="true" />
            </span>
            <h3 className="text-lg font-normal text-stone-900">
              {offset
                ? "No knowledge bases on this page"
                : "Create your first knowledge base"}
            </h3>
            <p className="mt-2 max-w-md text-sm leading-6 text-stone-500">
              Start a focused collection for the information your team needs.
            </p>
          </div>
        ) : (
          <>
            <div className="overflow-hidden rounded-2xl border border-stone-200 bg-white">
              {query.data.items.map((base) => (
                <Link
                  key={base.id}
                  to={`/workspaces/${workspaceId}/knowledge-bases/${base.id}`}
                  className="group flex items-center gap-4 border-b border-stone-100 px-5 py-4 transition-colors last:border-b-0 hover:bg-stone-50 sm:px-6"
                >
                  <span className="rounded-xl bg-teal-50 p-3 text-teal-700">
                    <BookOpen className="size-5" aria-hidden="true" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <h3 className="truncate text-base font-normal tracking-[-0.015em] text-stone-950 sm:text-lg">
                      {base.name}
                    </h3>
                    <p className="mt-1 text-xs text-stone-400">
                      Updated {new Date(base.updated_at).toLocaleDateString()}
                    </p>
                  </div>
                  <ArrowUpRight className="size-4 text-stone-300 transition-all group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:text-teal-700" />
                </Link>
              ))}
            </div>

            {(offset > 0 ||
              offset + query.data.limit < query.data.total) && (
              <nav
                aria-label="Knowledge base pages"
                className="mt-6 flex items-center justify-between border-t border-stone-200 pt-6"
              >
                <p className="text-sm text-stone-500">
                  {query.data.total} knowledge bases
                </p>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="icon"
                    aria-label="Previous page"
                    disabled={!offset}
                    onClick={() =>
                      setOffset(Math.max(0, offset - query.data.limit))
                    }
                  >
                    <ChevronLeft className="size-4" />
                  </Button>
                  <Button
                    variant="outline"
                    size="icon"
                    aria-label="Next page"
                    disabled={offset + query.data.limit >= query.data.total}
                    onClick={() => setOffset(offset + query.data.limit)}
                  >
                    <ChevronRight className="size-4" />
                  </Button>
                </div>
              </nav>
            )}
          </>
        )}
      </div>

      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent className="rounded-2xl p-6 sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-xl font-normal tracking-[-0.02em]">
              Create a knowledge base
            </DialogTitle>
            <DialogDescription>
              Choose a clear name for this collection of knowledge.
            </DialogDescription>
          </DialogHeader>
          <KnowledgeBaseForm
            workspaceId={workspaceId}
            onCancel={() => setCreating(false)}
            onSaved={(base) =>
              navigate(`/workspaces/${workspaceId}/knowledge-bases/${base.id}`)
            }
          />
        </DialogContent>
      </Dialog>
    </section>
  );
}
