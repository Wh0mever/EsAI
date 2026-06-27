export const CHAT_MODES = ["text-chat"] as const;
export type ChatMode = (typeof CHAT_MODES)[number];
