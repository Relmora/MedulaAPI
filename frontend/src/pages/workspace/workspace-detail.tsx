import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router";
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
import { KnowledgeBaseList } from "@/pages/knowledge-base/components/knowledge-base-list";
import { getErrorMessage } from "@/services/http";
import { getWorkspace } from "@/services/workspace";
import { WorkspaceDetailHeader } from "./components/workspace-detail-header";
import { WorkspaceForm } from "./components/workspace-form";

export default function WorkspaceDetail() {
  const { workspaceId = "" } = useParams();
  return <WorkspaceContent key={workspaceId} workspaceId={workspaceId} />;
}

function WorkspaceContent({ workspaceId }: { workspaceId: string }) {
  const [editing, setEditing] = useState(false);
  const query = useQuery({
    queryKey: ["workspace", workspaceId],
    queryFn: ({ signal }) => getWorkspace(workspaceId, signal),
  });

  if (query.isPending) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-28 rounded-2xl" />
        <Skeleton className="h-64 rounded-2xl" />
      </div>
    );
  }

  if (query.isError) {
    return (
      <Alert variant="destructive">
        <AlertDescription className="flex items-center justify-between gap-4">
          <span>{getErrorMessage(query.error)}</span>
          <Button variant="outline" onClick={() => void query.refetch()}>
            Try again
          </Button>
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <section>
      <WorkspaceDetailHeader
        workspace={query.data}
        onRename={() => setEditing(true)}
      />
      <KnowledgeBaseList workspaceId={workspaceId} />

      <Dialog open={editing} onOpenChange={setEditing}>
        <DialogContent className="rounded-2xl p-6 sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-xl font-normal tracking-[-0.02em]">
              Rename workspace
            </DialogTitle>
            <DialogDescription>
              Update the name used to identify this workspace.
            </DialogDescription>
          </DialogHeader>
          <WorkspaceForm
            workspace={query.data}
            onCancel={() => setEditing(false)}
            onSaved={() => setEditing(false)}
          />
        </DialogContent>
      </Dialog>
    </section>
  );
}
