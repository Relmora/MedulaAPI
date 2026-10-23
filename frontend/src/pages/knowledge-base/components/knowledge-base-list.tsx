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
import { getKnowledgeBases } from "@/services/knowledge-base";
import { getErrorMessage } from "@/services/http";
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
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Knowledge bases</h2>
        </CardTitle>
        <CardDescription>
          Create and manage knowledge inside this workspace.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <Button onClick={() => setCreating(true)} disabled={creating}>
          New knowledge base
        </Button>
        {creating && (
          <KnowledgeBaseForm
            workspaceId={workspaceId}
            onCancel={() => setCreating(false)}
            onSaved={(base) =>
              navigate(`/workspaces/${workspaceId}/knowledge-bases/${base.id}`)
            }
          />
        )}
        {query.isPending && (
          <Skeleton className="h-24" aria-label="Loading knowledge bases" />
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
                  ? "No knowledge bases on this page."
                  : "No knowledge bases yet. Create one to get started."}
              </CardDescription>
            )}
            {query.data.items.map((base) => (
              <Card key={base.id}>
                <CardHeader>
                  <CardTitle>
                    <Link
                      to={`/workspaces/${workspaceId}/knowledge-bases/${base.id}`}
                    >
                      {base.name}
                    </Link>
                  </CardTitle>
                  <CardDescription>
                    Updated {new Date(base.updated_at).toLocaleDateString()}
                  </CardDescription>
                </CardHeader>
              </Card>
            ))}
            {(offset > 0 || query.data.total > query.data.limit) && (
              <nav
                aria-label="Knowledge base pages"
                className="flex items-center gap-3"
              >
                <Button
                  variant="outline"
                  disabled={!offset}
                  onClick={() => setOffset(Math.max(0, offset - 20))}
                >
                  Previous
                </Button>
                <span className="text-sm">
                  {query.data.total} knowledge bases
                </span>
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
