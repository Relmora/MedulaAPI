import { useQuery } from "@tanstack/react-query";
import { Navigate } from "react-router";
import { getCurrentUser, sessionKey } from "@/services/auth";
import { LoginIntro } from "./components/login-intro";
import { LoginForm } from "./components/login-form";

export default function Login() {
  const session = useQuery({
    queryKey: sessionKey,
    queryFn: ({ signal }) => getCurrentUser(signal),
  });

  if (session.data) return <Navigate to="/workspaces" replace />;

  return (
    <main className="grid min-h-svh bg-stone-50 lg:grid-cols-2">
      <LoginIntro />
      <LoginForm
        isPending={session.isPending}
        sessionError={session.error}
        onRetry={() => void session.refetch()}
      />
    </main>
  );
}
