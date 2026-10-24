import { Layers3, LayoutGrid, LogOut, UserRound } from "lucide-react";
import { Link, NavLink } from "react-router";
import { Button } from "@/components/ui/button";

type AppSidebarProps = {
  username: string;
  isSigningOut: boolean;
  onSignOut: () => void;
};

export function AppSidebar({
  username,
  isSigningOut,
  onSignOut,
}: AppSidebarProps) {
  return (
    <aside className="hidden min-h-svh flex-col border-r border-stone-800 bg-stone-950 px-4 py-6 text-stone-300 lg:sticky lg:top-0 lg:flex lg:h-svh">
      <Link
        to="/workspaces"
        className="flex items-center gap-3 px-2 text-lg font-medium tracking-[-0.02em] text-white"
      >
        <span className="rounded-xl bg-white/10 p-2.5">
          <Layers3 className="size-5" aria-hidden="true" />
        </span>
        MedulaAPI
      </Link>

      <nav className="mt-12" aria-label="Main navigation">
        <p className="mb-3 px-3 text-[0.65rem] font-medium tracking-[0.18em] text-stone-600 uppercase">
          Workspace
        </p>
        <NavLink
          to="/workspaces"
          className={({ isActive }) =>
            `flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-colors ${
              isActive
                ? "bg-white text-stone-950"
                : "text-stone-400 hover:bg-white/5 hover:text-white"
            }`
          }
        >
          <LayoutGrid className="size-4" aria-hidden="true" />
          Workspaces
        </NavLink>
      </nav>

      <div className="mt-auto border-t border-stone-800 pt-5">
        <div className="mb-4 flex items-center gap-3 px-2">
          <span className="flex size-9 items-center justify-center rounded-full bg-teal-400/10 text-teal-300">
            <UserRound className="size-4" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <p className="truncate text-sm text-white">{username}</p>
            <p className="text-xs text-stone-500">Signed in</p>
          </div>
        </div>
        <Button
          variant="ghost"
          className="w-full justify-start rounded-xl text-stone-400 hover:bg-white/5 hover:text-white"
          disabled={isSigningOut}
          onClick={onSignOut}
        >
          <LogOut className="size-4" />
          {isSigningOut ? "Signing out…" : "Sign out"}
        </Button>
      </div>
    </aside>
  );
}
