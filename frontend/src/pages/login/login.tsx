import { useQuery } from "@tanstack/react-query";
import { Navigate } from "react-router";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { getCurrentUser, sessionKey } from "@/services/auth";
import { getErrorMessage } from "@/services/http";
import { LoginForm } from "./components/login-form";

export default function Login() {
  const session = useQuery({
    queryKey: sessionKey,
    queryFn: ({ signal }) => getCurrentUser(signal),
  });
  if (session.data) return <Navigate to="/workspaces" replace />;
  return (
    <main className="mx-auto max-w-sm px-4 py-16">
      <Card>
        <CardHeader>
          <CardTitle>
            <h1>MedulaAPI</h1>
          </CardTitle>
          <CardDescription>
            Sign in to manage your workspaces and knowledge bases.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {session.isPending ? (
            <Skeleton className="h-40" aria-label="Checking session" />
          ) : session.isError ? (
            <Alert variant="destructive">
              <AlertDescription>
                {getErrorMessage(session.error)}
                <Button
                  variant="outline"
                  onClick={() => void session.refetch()}
                >
                  Try again
                </Button>
              </AlertDescription>
            </Alert>
          ) : (
            <LoginForm />
          )}
        </CardContent>
      </Card>
    </main>
  );
}
