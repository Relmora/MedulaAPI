import { http, type Page } from "./http";
import type { Workspace } from "./workspace";

export type KnowledgeBase = Workspace & { workspace_id: string };
const path = (workspaceId: string) =>
  `/workspaces/${workspaceId}/knowledge-bases`;

export async function getKnowledgeBases(
  workspaceId: string,
  offset = 0,
  signal?: AbortSignal,
) {
  return (
    await http.get<Page<KnowledgeBase>>(path(workspaceId), {
      params: { limit: 20, offset },
      signal,
    })
  ).data;
}
export async function getKnowledgeBase(
  workspaceId: string,
  id: string,
  signal?: AbortSignal,
) {
  return (
    await http.get<KnowledgeBase>(`${path(workspaceId)}/${id}`, { signal })
  ).data;
}
export async function createKnowledgeBase(workspaceId: string, name: string) {
  return (await http.post<KnowledgeBase>(path(workspaceId), { name })).data;
}
export async function renameKnowledgeBase(
  workspaceId: string,
  id: string,
  name: string,
) {
  return (
    await http.patch<KnowledgeBase>(`${path(workspaceId)}/${id}`, { name })
  ).data;
}
