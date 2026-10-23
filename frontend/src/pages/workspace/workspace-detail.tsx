import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { getWorkspace } from "@/services/workspace";
import { getErrorMessage } from "@/services/http";
import { WorkspaceForm } from "./components/workspace-form";
import { KnowledgeBaseList } from "@/pages/knowledge-base/components/knowledge-base-list";

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
  return (
    <>
      <Button variant="link" render={<Link to="/workspaces" />}>
        All workspaces
      </Button>
      {query.isPending ? (
        <Skeleton className="h-24" aria-label="Loading workspace" />
      ) : query.isError ? (
        <Alert variant="destructive">
          <AlertDescription>
            {getErrorMessage(query.error)}
            <Button onClick={() => void query.refetch()}>Try again</Button>
          </AlertDescription>
        </Alert>
      ) : (
        <>
          <Card>
            <CardHeader>
              <CardTitle>
                <h1>{query.data.name}</h1>
              </CardTitle>
            </CardHeader>
            <CardContent>
              {editing ? (
                <WorkspaceForm
                  workspace={query.data}
                  onCancel={() => setEditing(false)}
                  onSaved={() => setEditing(false)}
                />
              ) : (
                <Button variant="outline" onClick={() => setEditing(true)}>
                  Rename workspace
                </Button>
              )}
            </CardContent>
          </Card>
          <KnowledgeBaseList workspaceId={workspaceId} />
        </>
      )}
    </>
  );
}
