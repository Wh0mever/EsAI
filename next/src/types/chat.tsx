export const CHAT_MODES = ["text-chat"] as const;
export type ChatMode = (typeof CHAT_MODES)[number];

export type ChatSource = {
  title?: string;
  url: string;
};

export type Message = {
  role: "user" | "assistant";
  content: string;
  variant?: "normal" | "warning" | "error";
  attachments?: any[];
  sources?: ChatSource[];
  meta?: Record<string, any>;
  link?: string;
  linkLabel?: string;
  linkSecondary?: string;
  linkSecondaryLabel?: string;
  id?: number | string;
  /** true while tokens are still streaming in (live response) */
  streaming?: boolean;
};
