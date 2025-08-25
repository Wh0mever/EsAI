export const CHAT_MODES = ["text-chat", "image-chat", "music-chat"] as const;
export type ChatMode = (typeof CHAT_MODES)[number];