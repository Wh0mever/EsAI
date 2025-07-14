export const languages = ["ru", "en", "kg"] as const;
export type Language = (typeof languages)[number];
