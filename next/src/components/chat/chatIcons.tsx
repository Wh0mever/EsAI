import type { ReactNode } from "react";
import {
  IoDocumentTextOutline,
  IoSearchOutline,
  IoLanguageOutline,
  IoCreateOutline,
  IoCodeSlashOutline,
  IoNewspaperOutline,
  IoListOutline,
  IoReaderOutline,
  IoGridOutline,
  IoSparklesOutline,
  IoBriefcaseOutline,
  IoBulbOutline,
  IoSchoolOutline,
} from "react-icons/io5";

/** Map preset iconKey -> icon node. Keeps chatPresets.ts free of JSX. */
const ICONS: Record<string, ReactNode> = {
  doc: <IoDocumentTextOutline />,
  search: <IoSearchOutline />,
  translate: <IoLanguageOutline />,
  pen: <IoCreateOutline />,
  code: <IoCodeSlashOutline />,
  article: <IoNewspaperOutline />,
  summary: <IoListOutline />,
  contract: <IoReaderOutline />,
  excel: <IoGridOutline />,
  improve: <IoSparklesOutline />,
  resume: <IoBriefcaseOutline />,
  ideas: <IoBulbOutline />,
  learning: <IoSchoolOutline />,
};

export function presetIcon(key: string): ReactNode {
  return ICONS[key] ?? <IoSparklesOutline />;
}
