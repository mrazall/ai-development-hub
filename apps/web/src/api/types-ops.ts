export type Attachment = {
  id: string;
  project_id: string;
  session_id: string;
  message_id: string | null;
  original_name: string;
  mime_type: string;
  size_bytes: number;
  created_at: string;
  expires_at: string | null;
  sent_at: string | null;
};

export type DeletionImpact = {
  tasks: number;
  sessions: number;
  active_sessions: number;
  events: number;
  attachments: number;
  knowledge: number;
  warning: string;
};
