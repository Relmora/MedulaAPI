import { useId, useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { getErrorMessage } from "@/services/http";
import {
  saveKnowledgeBase,
  type KnowledgeBaseFormProps,
} from "../utils/utils";

export function KnowledgeBaseForm({
  workspaceId,
  knowledgeBase,
  onSaved,
  onCancel,
}: KnowledgeBaseFormProps) {
  const id = useId();
  const queryClient = useQueryClient();
  const [name, setName] = useState(knowledgeBase?.name ?? "");
  const mutation = useMutation({
    mutationFn: (value: string) =>
      saveKnowledgeBase(workspaceId, value, knowledgeBase),
    onSuccess: (result) => {
      queryClient.setQueryData(
        ["knowledge-base", workspaceId, result.id],
        result,
      );
      void queryClient.invalidateQueries({
        queryKey: ["knowledge-bases", workspaceId],
      });
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
        <Label htmlFor={id} className="font-normal text-stone-700">
          Knowledge base name
        </Label>
        <Input
          id={id}
          autoFocus
          placeholder="e.g. Engineering handbook"
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
        <Button
          type="button"
          variant="outline"
          disabled={mutation.isPending}
          onClick={onCancel}
        >
          Cancel
        </Button>
        <Button type="submit" disabled={mutation.isPending}>
          {mutation.isPending
            ? "Saving…"
            : knowledgeBase
              ? "Save name"
              : "Create knowledge base"}
        </Button>
      </div>
    </form>
  );
}
