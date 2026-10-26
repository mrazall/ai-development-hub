import type { KnowledgeGraphResponse, SearchResponse } from './types';

export type KnowledgeDocumentSummary = {
  id: string;
  title: string;
  path: string;
  project_id: string | null;
  type: string;
  updated_at: string;
  excerpt: string;
};
export type KnowledgeDocumentList = { items: KnowledgeDocumentSummary[]; total: number; offset: number; limit: number };
export type KnowledgeDocument = KnowledgeDocumentSummary & { content: string; visibility: string };
export type { KnowledgeGraphResponse, SearchResponse };
