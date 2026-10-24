import { Layers3, LogOut } from "lucide-react";
import { Link } from "react-router";
import { Button } from "@/components/ui/button";

type MobileHeaderProps = {
  isSigningOut: boolean;
  onSignOut: () => void;
};

export function MobileHeader({
  isSigningOut,
  onSignOut,
}: MobileHeaderProps) {
  return (
    <header className="flex items-center justify-between border-b border-stone-200 bg-white px-5 py-4 lg:hidden">
      <Link
        to="/workspaces"
        className="flex items-center gap-2.5 font-medium tracking-[-0.02em]"
      >
        <span className="rounded-lg bg-stone-950 p-2 text-white">
          <Layers3 className="size-4" aria-hidden="true" />
        </span>
        MedulaAPI
      </Link>
      <Button
        variant="ghost"
        size="icon"
        aria-label="Sign out"
        disabled={isSigningOut}
        onClick={onSignOut}
      >
        <LogOut className="size-4" />
      </Button>
    </header>
  );
}
