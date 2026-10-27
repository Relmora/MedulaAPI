import { http } from "./http";

export const MAX_DOCUMENT_SIZE_BYTES = 25 * 1024 * 1024;

export type UploadInstructions = {
  url: string;
  method: "PUT" | "POST";
  headers: Record<string, string>;
  form_fields: Record<string, string> | null;
  expires_at: string;
};

export type DocumentUploadIntent = {
  document_id: string;
  upload: UploadInstructions;
};

function documentsPath(workspaceId: string, knowledgeBaseId: string) {
  return (
    `/workspaces/${workspaceId}/knowledge-bases/` +
    `${knowledgeBaseId}/documents`
  );
}

export function declaredContentType(file: File): string | null {
  if (file.type === "application/pdf") return file.type;
  if (file.type === "text/markdown") return file.type;
  if (file.type === "text/plain") return file.type;

  const extension = file.name.toLowerCase().split(".").pop();
  if (extension === "pdf") return "application/pdf";
  if (extension === "md" || extension === "markdown") return "text/markdown";
  if (extension === "txt") return "text/plain";
  return null;
}

export async function createDocumentUploadIntent(
  workspaceId: string,
  knowledgeBaseId: string,
  file: File,
): Promise<DocumentUploadIntent> {
  const contentType = declaredContentType(file);
  if (!contentType) throw new Error("Choose a PDF, Markdown, or text file.");
  if (file.size <= 0) throw new Error("The selected file is empty.");
  if (file.size > MAX_DOCUMENT_SIZE_BYTES)
    throw new Error("The selected file must be 25 MiB or smaller.");

  return (
    await http.post<DocumentUploadIntent>(
      `${documentsPath(workspaceId, knowledgeBaseId)}/upload-intent`,
      {
        original_filename: file.name,
        declared_content_type: contentType,
        declared_size_bytes: file.size,
      },
    )
  ).data;
}

export async function uploadDocument(
  workspaceId: string,
  knowledgeBaseId: string,
  file: File,
): Promise<DocumentUploadIntent> {
  const intent = await createDocumentUploadIntent(
    workspaceId,
    knowledgeBaseId,
    file,
  );
  const response = await fetch(intent.upload.url, {
    method: intent.upload.method,
    headers: intent.upload.headers,
    body: file,
  });
  if (!response.ok)
    throw new Error(
      "Storage rejected the upload. Select the file and try again.",
    );
  return intent;
}
