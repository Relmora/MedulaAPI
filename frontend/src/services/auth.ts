import axios, { type InternalAxiosRequestConfig } from "axios";
import { authHttp, http, isUnauthorized } from "./http";

export type User = { id: string; username: string; created_at: string };
export type Credentials = { username: string; password: string };
export const sessionKey = ["session"] as const;

type SessionRequest = InternalAxiosRequestConfig & {
  sessionVersion?: number;
  refreshVersion?: number;
  retried?: boolean;
};

let sessionVersion = 0;
let refreshVersion = 0;
let refreshing: Promise<void> | null = null;

export async function refreshSession() {
  if (!refreshing) {
    refreshing = authHttp
      .post("/auth/refresh", {})
      .then(() => {
        refreshVersion++;
      })
      .finally(() => {
        refreshing = null;
      });
  }
  return refreshing;
}


http.interceptors.request.use((config: SessionRequest) => {
  config.sessionVersion ??= sessionVersion;
  config.refreshVersion ??= refreshVersion;
  return config;
});
http.interceptors.response.use(
  (response) => {
    const config = response.config as SessionRequest;
    if (config.sessionVersion !== sessionVersion)
      throw new axios.CanceledError("Session changed");
    return response;
  },
  async (error) => {
    if (!axios.isAxiosError(error) || !error.config) throw error;
    const config = error.config as SessionRequest;
    if (config.signal?.aborted || config.sessionVersion !== sessionVersion)
      throw new axios.CanceledError("Request cancelled");
    if (!isUnauthorized(error) || config.retried) throw error;
    config.retried = true;
    try {
      if (config.refreshVersion === refreshVersion) await refreshSession();
    } catch (refreshError) {
      if (config.signal?.aborted || config.sessionVersion !== sessionVersion)
        throw new axios.CanceledError("Request cancelled");
      throw refreshError;
    }
    if (config.signal?.aborted || config.sessionVersion !== sessionVersion)
      throw new axios.CanceledError("Request cancelled");
    return http.request(config);
  },
);

export async function getCurrentUser(
  signal?: AbortSignal,
): Promise<User | null> {
  try {
    return (await http.get<User>("/auth/me", { signal })).data;
  } catch (error) {
    if (isUnauthorized(error)) return null;
    throw error;
  }
}

export async function login(credentials: Credentials) {
  if (refreshing) await refreshing.catch(() => {});
  const { data } = await authHttp.post<User>("/auth/login", credentials);
  sessionVersion++;
  return data;
}

export async function register(credentials: Credentials) {
  if (refreshing) await refreshing.catch(() => {});
  const { data } = await authHttp.post<User>("/auth/register", credentials);
  sessionVersion++;
  return data;
}

export async function logout() {
  if (refreshing) await refreshing.catch(() => {});
  await authHttp.post("/auth/logout", {});
  sessionVersion++;
}

export function expireSession() {
  sessionVersion++;
}
