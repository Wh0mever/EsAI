// chatPresets.ts
// Easily extensible definitions for Quick Actions and Scenario Cards.
// Each entry carries an i18n key (label) and a prompt template that is placed
// into the input when clicked. `iconKey` maps to an icon in the UI layer so this
// file stays free of JSX/react-icons.

export type QuickAction = {
  id: string;
  iconKey: string;
  /** i18n key for the visible label */
  labelKey: string;
  /** i18n key for the prompt template injected into the input */
  promptKey: string;
};

export type ScenarioCard = {
  id: string;
  iconKey: string;
  titleKey: string;
  descKey: string;
  promptKey: string;
};

export const QUICK_ACTIONS: QuickAction[] = [
  { id: "upload-doc", iconKey: "doc", labelKey: "chat.quick.upload_doc", promptKey: "chat.quick.upload_doc_prompt" },
  { id: "web-search", iconKey: "search", labelKey: "chat.quick.web_search", promptKey: "chat.quick.web_search_prompt" },
  { id: "translate", iconKey: "translate", labelKey: "chat.quick.translate", promptKey: "chat.quick.translate_prompt" },
  { id: "write-text", iconKey: "pen", labelKey: "chat.quick.write_text", promptKey: "chat.quick.write_text_prompt" },
  { id: "write-code", iconKey: "code", labelKey: "chat.quick.write_code", promptKey: "chat.quick.write_code_prompt" },
];

export const SCENARIO_CARDS: ScenarioCard[] = [
  { id: "article", iconKey: "article", titleKey: "chat.scenario.article", descKey: "chat.scenario.article_desc", promptKey: "chat.scenario.article_prompt" },
  { id: "summary", iconKey: "summary", titleKey: "chat.scenario.summary", descKey: "chat.scenario.summary_desc", promptKey: "chat.scenario.summary_prompt" },
  { id: "contract", iconKey: "contract", titleKey: "chat.scenario.contract", descKey: "chat.scenario.contract_desc", promptKey: "chat.scenario.contract_prompt" },
  { id: "translate-doc", iconKey: "translate", titleKey: "chat.scenario.translate_doc", descKey: "chat.scenario.translate_doc_desc", promptKey: "chat.scenario.translate_doc_prompt" },
  { id: "excel", iconKey: "excel", titleKey: "chat.scenario.excel", descKey: "chat.scenario.excel_desc", promptKey: "chat.scenario.excel_prompt" },
  { id: "improve", iconKey: "improve", titleKey: "chat.scenario.improve", descKey: "chat.scenario.improve_desc", promptKey: "chat.scenario.improve_prompt" },
  { id: "resume", iconKey: "resume", titleKey: "chat.scenario.resume", descKey: "chat.scenario.resume_desc", promptKey: "chat.scenario.resume_prompt" },
  { id: "ideas", iconKey: "ideas", titleKey: "chat.scenario.ideas", descKey: "chat.scenario.ideas_desc", promptKey: "chat.scenario.ideas_prompt" },
  { id: "code-help", iconKey: "code", titleKey: "chat.scenario.code_help", descKey: "chat.scenario.code_help_desc", promptKey: "chat.scenario.code_help_prompt" },
  { id: "learning", iconKey: "learning", titleKey: "chat.scenario.learning", descKey: "chat.scenario.learning_desc", promptKey: "chat.scenario.learning_prompt" },
];
