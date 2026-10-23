import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { ArrowRight, Layers3, LockKeyhole, UserRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { sessionKey, type Credentials } from "@/services/auth";
import { getErrorMessage } from "@/services/http";
import { authenticate, type FormState, type LoginFormProps } from "../utils/utils";


export function LoginForm({
  isPending,
  sessionError,
  onRetry,
}: LoginFormProps) {
  const queryClient = useQueryClient();

  const navigate = useNavigate();

  const [creatingAccount, setCreatingAccount] = useState(false);
  const [form, setForm] = useState<FormState>({
    username: "",
    password: "",
    validation: "",
  });

  const mutation = useMutation({
    mutationFn: (credentials: Credentials) => authenticate(credentials, creatingAccount),
    onSuccess: (user) => {
      queryClient.setQueryData(sessionKey, user);
      navigate("/workspaces", { replace: true });
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    mutation.mutate({ username: form.username, password: form.password });
  }

  return (
    <section className="flex min-h-svh items-center justify-center bg-[radial-gradient(circle_at_top_right,_rgba(20,184,166,0.08),_transparent_35%)] px-5 py-12 sm:px-10">
      <div className="w-full max-w-[29rem]">
        <div className="mb-8 flex items-center gap-3 text-xl font-medium lg:hidden">
          <span className="rounded-xl bg-stone-950 p-2 text-white">
            <Layers3 className="size-5" aria-hidden="true" />
          </span>
          MedulaAPI
        </div>

        <div>
          <header className="mb-9">
            <h2 className="text-4xl font-normal tracking-[-0.035em] text-stone-950 sm:text-[2.75rem]">
              {creatingAccount ? "Create your account" : "Welcome back"}
            </h2>
            <p className="mt-4 max-w-sm text-[0.95rem] leading-7 font-normal text-stone-500">
              {creatingAccount
                ? "Create an account to start organizing your knowledge."
                : "Enter your details to continue to your workspaces."}
            </p>
          </header>
          <div>
            {isPending ? (
              <Skeleton className="h-72" aria-label="Checking session" />
            ) : sessionError ? (
              <Alert variant="destructive">
                <AlertDescription className="space-y-3">
                  <p>{getErrorMessage(sessionError)}</p>
                  <Button variant="outline" onClick={onRetry}>
                    Try again
                  </Button>
                </AlertDescription>
              </Alert>
            ) : (
              <form onSubmit={submit}>
                <fieldset
                  disabled={mutation.isPending}
                  className="space-y-5 disabled:opacity-70"
                >
                  <div className="space-y-2">
                    <Label
                      htmlFor="username"
                      className="text-sm font-normal text-stone-700"
                    >
                      Username
                    </Label>
                    <div className="relative">
                      <UserRound className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-stone-400" />
                      <Input
                        id="username"
                        autoComplete="username"
                        placeholder="Enter your username"
                        required
                        maxLength={creatingAccount ? 64 : 128}
                        value={form.username}
                        onChange={(event) =>
                          setForm((current) => ({
                            ...current,
                            username: event.target.value,
                            validation: "",
                          }))
                        }
                        className="h-12 rounded-xl border-stone-200 bg-stone-50/70 pl-10 shadow-none transition-colors focus-visible:border-teal-500 focus-visible:ring-teal-500/15"
                      />
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label
                      htmlFor="password"
                      className="text-sm font-normal text-stone-700"
                    >
                      Password
                    </Label>
                    <div className="relative">
                      <LockKeyhole className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-stone-400" />
                      <Input
                        id="password"
                        type="password"
                        placeholder="Enter your password"
                        autoComplete={
                          creatingAccount ? "new-password" : "current-password"
                        }
                        required
                        value={form.password}
                        onChange={(event) =>
                          setForm((current) => ({
                            ...current,
                            password: event.target.value,
                            validation: "",
                          }))
                        }
                        className="h-12 rounded-xl border-stone-200 bg-stone-50/70 pl-10 shadow-none transition-colors focus-visible:border-teal-500 focus-visible:ring-teal-500/15"
                      />
                    </div>
                  </div>
                  {creatingAccount && (
                    <p className="-mt-2 text-xs text-muted-foreground">
                      Password: 15–128 characters.
                    </p>
                  )}
                  {(form.validation || mutation.isError) && (
                    <Alert variant="destructive">
                      <AlertDescription>
                        {form.validation || getErrorMessage(mutation.error)}
                      </AlertDescription>
                    </Alert>
                  )}
                  <Button
                    type="submit"
                    className="group h-12 w-full rounded-xl bg-stone-950 font-normal text-white shadow-lg shadow-stone-950/15 hover:bg-teal-700"
                  >
                    <span>
                      {mutation.isPending
                        ? "Please wait…"
                        : creatingAccount
                          ? "Create account"
                          : "Sign in"}
                    </span>
                    {!mutation.isPending && (
                      <ArrowRight className="size-4 transition-transform group-hover:translate-x-1" />
                    )}
                  </Button>
                  <div className="flex items-center gap-3 text-xs text-stone-400">
                    <span className="h-px flex-1 bg-stone-200" />
                    {creatingAccount ? "Already registered?" : "New here?"}
                    <span className="h-px flex-1 bg-stone-200" />
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    className="h-11 w-full rounded-xl border-stone-200 bg-white font-normal text-stone-700 hover:border-stone-300 hover:bg-stone-50"
                    onClick={() => {
                      setCreatingAccount(!creatingAccount);
                      setForm({
                        username: "",
                        password: "",
                        validation: "",
                      });
                      mutation.reset();
                    }}
                  >
                    {creatingAccount
                      ? "Already have an account? Sign in"
                      : "Create an account"}
                  </Button>
                </fieldset>
              </form>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
