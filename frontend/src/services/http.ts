import axios from "axios";

const config = {
  baseURL: import.meta.env.VITE_API_BASE_URL,
  withCredentials: true,
  timeout: 15000,
};


export const authHttp = axios.create(config);
export const http = axios.create(config);

for (const client of [authHttp, http]) {
  client.interceptors.request.use((config) => {
    if (!config.baseURL)
      throw new Error("Set VITE_API_BASE_URL in .env.local and restart Vite.");
    return config;
  });
}

export function isUnauthorized(error: unknown) {
  return axios.isAxiosError(error) && error.response?.status === 401;
}

export function getErrorMessage(error: unknown): string {
  if (!axios.isAxiosError(error))
    return error instanceof Error ? error.message : "Something went wrong.";
  if (!error.response)
    return "Could not reach MedulaAPI. Check your connection and try again.";
  const code = error.response.data?.error?.code;
  const messages: Record<string, string> = {
    INVALID_CREDENTIALS: "The username or password is incorrect.",
    REGISTRATION_DISABLED: "Registration is currently closed.",
    DOCUMENT_UPLOAD_INCOMPLETE:
      "Storage could not find the uploaded file. Select it and try again.",
    DOCUMENT_UPLOAD_MISMATCH:
      "The stored file did not match the selected file. Please try again.",
    DOCUMENT_UPLOAD_STATE: "This upload cannot be completed again.",
    USERNAME_UNAVAILABLE: "That username is unavailable.",
    UNTRUSTED_ORIGIN:
      "The API rejected this browser origin. Check that both URLs use the same hostname and the frontend origin is allowed.",
  };
  if (messages[code]) return messages[code];
  switch (error.response.status) {
    case 401:
      return "Your session has expired. Please sign in again.";
    case 403:
      return "You do not have permission to perform this action.";
    case 404:
      return "This resource is unavailable or you do not have access.";
    case 422:
      return "Check the entered values and try again.";
    case 429:
      return "Too many requests. Please try again shortly.";
    default:
      return "The request could not be completed. Please try again.";
  }
}

export type Page<T> = {
  items: T[];
  limit: number;
  offset: number;
  total: number;
};
