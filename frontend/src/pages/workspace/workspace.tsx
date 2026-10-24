import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { getErrorMessage } from "@/services/http";
import { getWorkspaces } from "@/services/workspace";
import { WorkspaceForm } from "./components/workspace-form";
import { WorkspaceHeader } from "./components/workspace-header";
import { WorkspaceList } from "./components/workspace-list";

export default function Workspaces() {
  const [offset, setOffset] = useState(0);
  const [creating, setCreating] = useState(false);
  const navigate = useNavigate();
  
  const query = useQuery({
    queryKey: ["workspaces", offset],
    queryFn: ({ signal }) => getWorkspaces(offset, signal),
  });

  return (
    <section>
      <WorkspaceHeader total={query.data?.total} onCreate={() => setCreating(true)} />
      <div className="mt-7">
        {query.isPending ? (
          <div className="space-y-3">
            {[0, 1, 2].map((item) => <Skeleton key={item} className="h-24 rounded-xl" />)}
          </div>
        ) : query.isError ? (
          <Alert variant="destructive">
            <AlertDescription className="flex items-center justify-between gap-4">
              <span>{getErrorMessage(query.error)}</span>
              <Button variant="outline" onClick={() => void query.refetch()}>Try again</Button>
            </AlertDescription>
          </Alert>
        ) : (
          <WorkspaceList page={query.data} offset={offset} onOffsetChange={setOffset} />
        )}
      </div>

      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent className="rounded-2xl p-6 sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-xl font-normal tracking-[-0.02em]">Create a workspace</DialogTitle>
            <DialogDescription>Give this workspace a clear name. You can rename it later.</DialogDescription>
          </DialogHeader>
          <WorkspaceForm onCancel={() => setCreating(false)} onSaved={(workspace) => navigate(`/workspaces/${workspace.id}`)} />
        </DialogContent>
      </Dialog>
    </section>
  );
}
