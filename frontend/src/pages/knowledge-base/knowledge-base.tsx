import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router";
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
import { getKnowledgeBase } from "@/services/knowledge-base";
import { getErrorMessage } from "@/services/http";
import { DocumentUpload } from "./components/document-upload";
import { KnowledgeBaseForm } from "./components/knowledge-base-form";

export default function KnowledgeBaseDetail() {
  const { workspaceId = "", knowledgeBaseId = "" } = useParams();
  return (
    <KnowledgeBaseContent
      key={`${workspaceId}:${knowledgeBaseId}`}
      workspaceId={workspaceId}
      knowledgeBaseId={knowledgeBaseId}
    />
  );
}

function KnowledgeBaseContent({
  workspaceId,
  knowledgeBaseId,
}: {
  workspaceId: string;
  knowledgeBaseId: string;
}) {
  const [editing, setEditing] = useState(false);
  const [saved, setSaved] = useState(false);
  const query = useQuery({
    queryKey: ["knowledge-base", workspaceId, knowledgeBaseId],
    queryFn: ({ signal }) =>
      getKnowledgeBase(workspaceId, knowledgeBaseId, signal),
  });
  return (
    <>
      <Button
        variant="link"
        nativeButton={false}
        render={<Link to={`/workspaces/${workspaceId}`} />}
      >
        Back to workspace
      </Button>
      {query.isPending ? (
        <Skeleton className="h-24" aria-label="Loading knowledge base" />
      ) : query.isError ? (
        <Alert variant="destructive">
          <AlertDescription>
            {getErrorMessage(query.error)}
            <Button onClick={() => void query.refetch()}>Try again</Button>
          </AlertDescription>
        </Alert>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>
              <h1>{query.data.name}</h1>
            </CardTitle>
            <CardDescription>Knowledge base</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {editing ? (
              <KnowledgeBaseForm
                workspaceId={workspaceId}
                knowledgeBase={query.data}
                onCancel={() => setEditing(false)}
                onSaved={() => {
                  setEditing(false);
                  setSaved(true);
                }}
              />
            ) : (
              <Button
                variant="outline"
                onClick={() => {
                  setEditing(true);
                  setSaved(false);
                }}
              >
                Rename knowledge base
              </Button>
            )}
            {saved && (
              <Alert role="status">
                <AlertDescription>Knowledge base renamed.</AlertDescription>
              </Alert>
            )}
            <p className="text-sm">
              Created: {new Date(query.data.created_at).toLocaleString()}
            </p>
            <p className="text-sm">
              Updated: {new Date(query.data.updated_at).toLocaleString()}
            </p>
            <DocumentUpload
              workspaceId={workspaceId}
              knowledgeBaseId={knowledgeBaseId}
            />
          </CardContent>
        </Card>
      )}
    </>
  );
}
