import { useId, useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  createWorkspace,
  renameWorkspace,
  type Workspace,
} from "@/services/workspace";
import { getErrorMessage } from "@/services/http";

export function WorkspaceForm({
  workspace,
  onSaved,
  onCancel,
}: {
  workspace?: Workspace;
  onSaved: (workspace: Workspace) => void;
  onCancel: () => void;
}) {
  const id = useId();
  const queryClient = useQueryClient();
  const [name, setName] = useState(workspace?.name ?? "");
  const [validation, setValidation] = useState("");
  const mutation = useMutation({
    mutationFn: (name: string) =>
      workspace ? renameWorkspace(workspace.id, name) : createWorkspace(name),
    onSuccess: (result) => {
      queryClient.setQueryData(["workspace", result.id], result);
      void queryClient.invalidateQueries({ queryKey: ["workspaces"] });
      onSaved(result);
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    if (mutation.isPending) return;
    const value = name.trim();
    if (!value || [...value].length > 100) {
      setValidation("Enter a name between 1 and 100 characters.");
      return;
    }
    setValidation("");
    mutation.mutate(value);
  }
  return (
    <form onSubmit={submit} className="space-y-4">
      <Label htmlFor={id}>Workspace name</Label>
      <Input
        id={id}
        value={name}
        onChange={(e) => setName(e.target.value)}
        disabled={mutation.isPending}
        aria-invalid={!!validation}
      />
      {(validation || mutation.isError) && (
        <Alert variant="destructive">
          <AlertDescription>
            {validation || getErrorMessage(mutation.error)}
          </AlertDescription>
        </Alert>
      )}
      <Button type="submit" disabled={mutation.isPending}>
        {mutation.isPending
          ? "Saving…"
          : workspace
            ? "Save name"
            : "Create workspace"}
      </Button>{" "}
      <Button
        type="button"
        variant="outline"
        disabled={mutation.isPending}
        onClick={onCancel}
      >
        Cancel
      </Button>
    </form>
  );
}
