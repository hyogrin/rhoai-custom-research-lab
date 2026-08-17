export const SUPPORTED_LANGUAGES = {
  "en-US": "English",
  "ko-KR": "한국어",
} as const;

export type SupportedLanguage = keyof typeof SUPPORTED_LANGUAGES;

export const LANGUAGE_INSTRUCTIONS: Record<SupportedLanguage, string> = {
  "en-US": "You MUST respond entirely in English.",
  "ko-KR": "반드시 한국어로 답변하세요.",
};

export function getLanguageInstruction(lang: SupportedLanguage): string {
  return LANGUAGE_INSTRUCTIONS[lang] || LANGUAGE_INSTRUCTIONS["en-US"];
}
