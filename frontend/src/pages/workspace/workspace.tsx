import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { getWorkspaces } from "@/services/workspace";
import { getErrorMessage } from "@/services/http";
import { WorkspaceForm } from "./components/workspace-form";

export default function Workspaces() {
  const [offset, setOffset] = useState(0);
  const [creating, setCreating] = useState(false);
  const navigate = useNavigate();
  const query = useQuery({
    queryKey: ["workspaces", offset],
    queryFn: ({ signal }) => getWorkspaces(offset, signal),
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h1>Workspaces</h1>
        </CardTitle>
        <CardDescription>
          Organize your knowledge bases by project.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <Button onClick={() => setCreating(true)} disabled={creating}>
          New workspace
        </Button>
        {creating && (
          <WorkspaceForm
            onCancel={() => setCreating(false)}
            onSaved={(workspace) => navigate(`/workspaces/${workspace.id}`)}
          />
        )}
        {query.isPending && (
          <Skeleton className="h-24" aria-label="Loading workspaces" />
        )}
        {query.isError && (
          <Alert variant="destructive">
            <AlertDescription>
              {getErrorMessage(query.error)}
              <Button variant="outline" onClick={() => void query.refetch()}>
                Try again
              </Button>
            </AlertDescription>
          </Alert>
        )}
        {query.data && !query.isError && (
          <>
            {!query.data.items.length && (
              <CardDescription>
                {offset
                  ? "No workspaces on this page."
                  : "No workspaces yet. Create one to get started."}
              </CardDescription>
            )}
            {query.data.items.map((workspace) => (
              <Card key={workspace.id}>
                <CardHeader>
                  <CardTitle>
                    <Link to={`/workspaces/${workspace.id}`}>
                      {workspace.name}
                    </Link>
                  </CardTitle>
                  <CardDescription>
                    Created{" "}
                    {new Date(workspace.created_at).toLocaleDateString()}
                  </CardDescription>
                </CardHeader>
              </Card>
            ))}
            {(offset > 0 || query.data.total > query.data.limit) && (
              <nav
                aria-label="Workspace pages"
                className="flex items-center gap-3"
              >
                <Button
                  variant="outline"
                  disabled={!offset}
                  onClick={() => setOffset(Math.max(0, offset - 20))}
                >
                  Previous
                </Button>
                <span className="text-sm">{query.data.total} workspaces</span>
                <Button
                  variant="outline"
                  disabled={offset + query.data.limit >= query.data.total}
                  onClick={() => setOffset(offset + 20)}
                >
                  Next
                </Button>
              </nav>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
