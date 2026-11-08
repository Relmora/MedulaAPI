import { useId, useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { Network, Upload } from "lucide-react";
import { Link } from "react-router";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { getErrorMessage } from "@/services/http";
import { uploadDocument } from "@/services/document";

type DocumentUploadProps = {
  workspaceId: string;
  knowledgeBaseId: string;
};

export function DocumentUpload({
  workspaceId,
  knowledgeBaseId,
}: DocumentUploadProps) {
  const inputId = useId();
  const [file, setFile] = useState<File | null>(null);
  const mutation = useMutation({
    mutationFn: (selectedFile: File) =>
      uploadDocument(workspaceId, knowledgeBaseId, selectedFile),
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;
    mutation.mutate(file);
  }

  return (
    <form onSubmit={submit} className="space-y-4 rounded-xl border p-4">
      <div className="space-y-1">
        <h2 className="font-medium">Upload a document</h2>
        <p className="text-sm text-muted-foreground">
          PDF, Markdown, or text files up to 25 MiB.
        </p>
      </div>
      <div className="space-y-2">
        <Label htmlFor={inputId}>Document</Label>
        <Input
          id={inputId}
          type="file"
          accept=".pdf,.md,.markdown,.txt,application/pdf,text/markdown,text/plain"
          disabled={mutation.isPending}
          onChange={(event) => {
            setFile(event.target.files?.[0] ?? null);
            mutation.reset();
          }}
        />
      </div>
      {mutation.isError && (
        <Alert variant="destructive">
          <AlertDescription>{getErrorMessage(mutation.error)}</AlertDescription>
        </Alert>
      )}
      {mutation.isSuccess && (
        <Alert role="status">
          <Network className="size-4" />
          <AlertTitle>Upload complete</AlertTitle>
          <AlertDescription className="space-y-3">
            <p>
              The document is queued for processing. Its entities will appear
              in the knowledge-base graph when they are ready.
            </p>
            <Button
              variant="outline"
              nativeButton={false}
              render={
                <Link
                  to={`/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}/graph`}
                />
              }
            >
              <Network className="size-4" />
              View knowledge base graph
            </Button>
          </AlertDescription>
        </Alert>
      )}
      <Button type="submit" disabled={!file || mutation.isPending}>
        <Upload className="size-4" />
        {mutation.isPending ? "Uploading…" : "Upload"}
      </Button>
    </form>
  );
}
