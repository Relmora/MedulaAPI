import { z } from "zod";
import {
  createKnowledgeBase,
  renameKnowledgeBase,
  type KnowledgeBase,
} from "@/services/knowledge-base";

export type KnowledgeBaseFormProps = {
  workspaceId: string;
  knowledgeBase?: KnowledgeBase;
  onSaved: (knowledgeBase: KnowledgeBase) => void;
  onCancel: () => void;
};

const knowledgeBaseSchema = z
  .string()
  .trim()
  .min(1, "Enter a knowledge base name.")
  .max(100, "Knowledge base name must be no more than 100 characters.");

export function saveKnowledgeBase(
  workspaceId: string,
  name: string,
  knowledgeBase?: KnowledgeBase,
) {
  const validatedName = knowledgeBaseSchema.parse(name);

  return knowledgeBase
    ? renameKnowledgeBase(workspaceId, knowledgeBase.id, validatedName)
    : createKnowledgeBase(workspaceId, validatedName);
}
