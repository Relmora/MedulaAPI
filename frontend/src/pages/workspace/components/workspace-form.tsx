import { useId, useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { getErrorMessage } from "@/services/http";
import { saveWorkspace, type WorkspaceFormProps } from "../utils/utils";

export function WorkspaceForm({ workspace, onSaved, onCancel }: WorkspaceFormProps) {
  const id = useId();
  const queryClient = useQueryClient();
  const [name, setName] = useState(workspace?.name ?? "");
  
  const mutation = useMutation({
    mutationFn: (value: string) => saveWorkspace(value, workspace),
    onSuccess: (result) => {
      queryClient.setQueryData(["workspace", result.id], result);
      void queryClient.invalidateQueries({ queryKey: ["workspaces"] });
      onSaved(result);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    mutation.mutate(name);
  }

  return (
    <form onSubmit={submit} className="space-y-5">
      <div className="space-y-2">
        <Label htmlFor={id} className="font-normal text-stone-700">Workspace name</Label>
        <Input
          id={id}
          autoFocus
          placeholder="e.g. Product research"
          value={name}
          onChange={(event) => setName(event.target.value)}
          disabled={mutation.isPending}
          aria-invalid={mutation.isError}
          className="h-11 rounded-xl border-stone-200 bg-stone-50/70"
        />
      </div>
      {mutation.isError && (
        <Alert variant="destructive">
          <AlertDescription>{getErrorMessage(mutation.error)}</AlertDescription>
        </Alert>
      )}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" disabled={mutation.isPending} onClick={onCancel}>Cancel</Button>
        <Button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? "Saving…" : workspace ? "Save name" : "Create workspace"}
        </Button>
      </div>
    </form>
  );
}
