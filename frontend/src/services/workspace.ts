import { http, type Page } from "./http";

export type Workspace = {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
};

export async function getWorkspaces(offset = 0, signal?: AbortSignal) {
  return (
    await http.get<Page<Workspace>>("/workspaces", {
      params: { limit: 20, offset },
      signal,
    })
  ).data;
}
export async function getWorkspace(id: string, signal?: AbortSignal) {
  return (await http.get<Workspace>(`/workspaces/${id}`, { signal })).data;
}
export async function createWorkspace(name: string) {
  return (await http.post<Workspace>("/workspaces", { name })).data;
}
export async function renameWorkspace(id: string, name: string) {
  return (await http.patch<Workspace>(`/workspaces/${id}`, { name })).data;
}
