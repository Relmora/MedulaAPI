import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";

type WorkspaceHeaderProps = { total?: number; onCreate: () => void };

export function WorkspaceHeader({ total, onCreate }: WorkspaceHeaderProps) {
  return (
    <header className="flex flex-col gap-5 border-b border-stone-200 pb-7 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <p className="mb-2 text-xs font-medium tracking-[0.16em] text-teal-700 uppercase">Your workspace</p>
        <h1 className="text-3xl font-normal tracking-[-0.035em] text-stone-950 sm:text-4xl">Workspaces</h1>
        <p className="mt-2 max-w-xl text-sm leading-6 text-stone-500">
          Keep projects and their knowledge bases organized in focused spaces.
          {typeof total === "number" && ` ${total} total.`}
        </p>
      </div>
      <Button onClick={onCreate} className="h-11 rounded-xl bg-stone-950 px-5 font-normal text-white shadow-lg shadow-stone-950/10 hover:bg-teal-700">
        <Plus className="size-4" />
        New workspace
      </Button>
    </header>
  );
}
