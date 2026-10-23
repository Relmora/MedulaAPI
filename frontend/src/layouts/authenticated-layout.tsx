import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, Navigate, Outlet, useLocation, useNavigate } from "react-router";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import { getCurrentUser, logout, sessionKey } from "@/services/auth";
import { getErrorMessage } from "@/services/http";

export default function AuthenticatedLayout() {
  const queryClient = useQueryClient();
  const location = useLocation();
  const navigate = useNavigate();
  const session = useQuery({
    queryKey: sessionKey,
    queryFn: ({ signal }) => getCurrentUser(signal),
  });
  const signOut = useMutation({
    mutationFn: logout,
    onSuccess: async () => {
      await queryClient.cancelQueries();
      queryClient.removeQueries({
        predicate: (query) => query.queryKey[0] !== "session",
      });
      queryClient.setQueryData(sessionKey, null);
      navigate("/login", { replace: true });
    },
  });
  if (session.isPending)
    return (
      <main className="p-6">
        <Skeleton className="h-24" aria-label="Checking session" />
      </main>
    );
  if (!session.isError && !session.data)
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  if (session.isError)
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
  return (
    <main className="mx-auto max-w-5xl space-y-6 p-4 md:p-6">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4">
          <CardTitle>
            <Link to="/workspaces">MedulaAPI</Link>
          </CardTitle>
          <Button
            variant="outline"
            disabled={signOut.isPending}
            onClick={() => signOut.mutate()}
          >
            {signOut.isPending ? "Signing out…" : "Sign out"}
          </Button>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Signed in as {session.data?.username}
          </p>
        </CardContent>
      </Card>
      {signOut.isError && (
        <Alert variant="destructive">
          <AlertDescription>{getErrorMessage(signOut.error)}</AlertDescription>
        </Alert>
      )}
      <Separator />
      <Outlet />
    </main>
  );
}
