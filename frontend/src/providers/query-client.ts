import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";
import { expireSession, sessionKey } from "@/services/auth";
import { isUnauthorized } from "@/services/http";

function handleSessionError(error: unknown) {
  if (!isUnauthorized(error)) return;
  expireSession();
  void queryClient.cancelQueries();
  queryClient.removeQueries({
    predicate: (query) => query.queryKey[0] !== "session",
  });
  queryClient.setQueryData(sessionKey, null);
}

export const queryClient = new QueryClient({
  queryCache: new QueryCache({ onError: handleSessionError }),
  mutationCache: new MutationCache({ onError: handleSessionError }),
  defaultOptions: {
    queries: { retry: false, staleTime: 30000 },
    mutations: { retry: false },
  },
});
