import { ArrowLeft, Pencil } from "lucide-react";
import { Link } from "react-router";
import { Button } from "@/components/ui/button";
import type { Workspace } from "@/services/workspace";

type WorkspaceDetailHeaderProps = {
  workspace: Workspace;
  onRename: () => void;
};

export function WorkspaceDetailHeader({
  workspace,
  onRename,
}: WorkspaceDetailHeaderProps) {
  return (
    <header className="border-b border-stone-200 pb-8">
      <Link
        to="/workspaces"
        className="inline-flex items-center gap-2 text-sm text-stone-500 transition-colors hover:text-stone-950"
      >
        <ArrowLeft className="size-4" />
        All workspaces
      </Link>
      <div className="mt-7 grid gap-5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
        <div>
          <p className="mb-2 text-xs font-medium tracking-[0.16em] text-teal-700 uppercase">
            Workspace
          </p>
          <h1 className="text-3xl font-normal tracking-[-0.035em] text-stone-950 sm:text-4xl">
            {workspace.name}
          </h1>
          <p className="mt-2 text-sm leading-6 text-stone-500">
            Create and manage the knowledge bases for this workspace.
          </p>
        </div>
        <Button
          variant="outline"
          className="h-10 rounded-xl bg-white font-normal sm:mt-6"
          onClick={onRename}
        >
          <Pencil className="size-4" />
          Rename
        </Button>
      </div>
    </header>
  );
}
