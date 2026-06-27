export const CHAT_MODES = ["text-chat"] as const;
export type ChatMode = (typeof CHAT_MODES)[number];

export type Message = {
  role: "user" | "assistant";
  content: string;
  variant?: "normal" | "warning" | "error";
  attachments?: any[];
  meta?: Record<string, any>;
  link?: string;
  linkLabel?: string;
  linkSecondary?: string;
  linkSecondaryLabel?: string;
  id?: number | string;
};
