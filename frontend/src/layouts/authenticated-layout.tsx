import { useMutation, useQuery } from "@tanstack/react-query";
import { Navigate, Outlet, useLocation, useNavigate } from "react-router";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { getCurrentUser, logout, sessionKey } from "@/services/auth";
import { getErrorMessage } from "@/services/http";
import { AppSidebar } from "./components/app-sidebar";
import { MobileHeader } from "./components/mobile-header";

export default function AuthenticatedLayout() {
  const location = useLocation();
  
  const navigate = useNavigate();

  const session = useQuery({
    queryKey: sessionKey,
    queryFn: ({ signal }) => getCurrentUser(signal),
  });

  const signOut = useMutation({
    mutationFn: logout,
    onSuccess: () => {
      navigate("/login", { replace: true });
    },
  });

  if (session.isPending) {
    return (
      <main className="p-6">
        <Skeleton className="h-24" aria-label="Checking session" />
      </main>
    );
  }

  if (session.isError) {
    return (
      <main className="p-6">
        <Alert variant="destructive">
          <AlertDescription>
            {getErrorMessage(session.error)}
            <Button onClick={() => void session.refetch()}>Try again</Button>
          </AlertDescription>
        </Alert>
      </main>
    );
  }

  if (!session.data) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }

  const handleSignOut = () => signOut.mutate();

  return (
    <div className="min-h-svh bg-stone-50 lg:grid lg:grid-cols-[17rem_minmax(0,1fr)]">
      <AppSidebar
        username={session.data.username}
        isSigningOut={signOut.isPending}
        onSignOut={handleSignOut}
      />
      <div className="min-w-0">
        <MobileHeader
          isSigningOut={signOut.isPending}
          onSignOut={handleSignOut}
        />
        <main className="mx-auto w-full max-w-7xl px-5 py-8 sm:px-8 lg:px-10 lg:py-10">
          {signOut.isError && (
            <Alert variant="destructive" className="mb-6">
              <AlertDescription>
                {getErrorMessage(signOut.error)}
              </AlertDescription>
            </Alert>
          )}
          <Outlet />
        </main>
      </div>
    </div>
  );
}
