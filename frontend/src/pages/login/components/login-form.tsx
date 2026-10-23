import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { login, register, sessionKey, type Credentials } from "@/services/auth";
import { getErrorMessage } from "@/services/http";

export function LoginForm() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const [creatingAccount, setCreatingAccount] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [validation, setValidation] = useState("");
  const mutation = useMutation({
    mutationFn: (credentials: Credentials) =>
      creatingAccount ? register(credentials) : login(credentials),
    onSuccess: async (user) => {
      await queryClient.cancelQueries();
      queryClient.removeQueries({
        predicate: (query) => query.queryKey[0] !== "session",
      });
      queryClient.setQueryData(sessionKey, user);
      const from = location.state?.from;
      navigate(
        typeof from === "string" && from.startsWith("/workspaces")
          ? from
          : "/workspaces",
        { replace: true },
      );
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    if (mutation.isPending) return;
    const name = username.trim().toLowerCase();
    if (
      creatingAccount &&
      (!/^[a-z0-9_.-]{3,64}$/.test(name) || [...password].length < 15)
    ) {
      setValidation(
        "Use a username of 3–64 letters, numbers, _, . or - and a password of 15–128 characters.",
      );
      return;
    }
    if (!name || !password || [...password].length > 128) {
      setValidation("Enter a username and a password of up to 128 characters.");
      return;
    }
    setValidation("");
    mutation.mutate({ username: name, password });
  }
  return (
    <form onSubmit={submit} className="space-y-4">
      <fieldset disabled={mutation.isPending} className="space-y-4">
        <Label htmlFor="username">Username</Label>
        <Input
          id="username"
          autoComplete="username"
          required
          maxLength={creatingAccount ? 64 : 128}
          value={username}
          onChange={(e) => setUsername(e.target.value)}
        />
        <Label htmlFor="password">Password</Label>
        <Input
          id="password"
          type="password"
          autoComplete={creatingAccount ? "new-password" : "current-password"}
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {creatingAccount && (
          <p className="text-sm text-muted-foreground">
            Password: 15–128 characters.
          </p>
        )}
        {(validation || mutation.isError) && (
          <Alert variant="destructive">
            <AlertDescription>
              {validation || getErrorMessage(mutation.error)}
            </AlertDescription>
          </Alert>
        )}
        <Button type="submit" className="w-full">
          {mutation.isPending
            ? "Please wait…"
            : creatingAccount
              ? "Create account"
              : "Sign in"}
        </Button>
        <Button
          type="button"
          variant="link"
          className="w-full"
          onClick={() => {
            setCreatingAccount(!creatingAccount);
            setPassword("");
            setValidation("");
            mutation.reset();
          }}
        >
          {creatingAccount
            ? "Already have an account? Sign in"
            : "Create an account"}
        </Button>
      </fieldset>
    </form>
  );
}
