import { z } from "zod";
import { createWorkspace, renameWorkspace, type Workspace } from "@/services/workspace";

export type WorkspaceFormProps = {
  workspace?: Workspace;
  onSaved: (workspace: Workspace) => void;
  onCancel: () => void;
};

const workspaceSchema = z.string().trim().min(1, "Enter a workspace name.").max(100, "Workspace name must be no more than 100 characters.");

export function saveWorkspace(name: string, workspace?: Workspace) {
  const validatedName = workspaceSchema.parse(name);
  return workspace ? renameWorkspace(workspace.id, validatedName) : createWorkspace(validatedName);
}
