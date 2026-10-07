"use client";

import { FiLock, FiPlus } from "react-icons/fi";
import { Badge, CARD, Preview, btn, fmtDate, mediaFacts } from "./parts";
import type { Candidate } from "./showcaseAdmin";

type Props = {
  candidate: Candidate;
  onAdd: (candidate: Candidate) => void;
};

export default function CandidateCard({ candidate, onAdd }: Props) {
  return (
    <li className={`${CARD} flex flex-col overflow-hidden`}>
      <Preview media={candidate} />
      <div className="flex flex-1 flex-col gap-2 p-3">
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-semibold text-foreground">
              {candidate.modelName || "Модель не указана"}
            </div>
            <div className="truncate text-[11px] text-muted-2">{mediaFacts(candidate)}</div>
          </div>
          {candidate.staff && <Badge>сотрудник</Badge>}
        </div>
        <p className="line-clamp-3 break-words text-xs text-muted" title={candidate.prompt || undefined}>
          {candidate.prompt || "Без текста запроса"}
        </p>
        <div className="truncate text-[11px] text-muted-2">
          {[candidate.authorEmail, candidate.finishedAt ? fmtDate(candidate.finishedAt) : ""].filter(Boolean).join(" · ")}
        </div>
        <div className="mt-auto pt-1">
          {candidate.publishable ? (
            <button type="button" onClick={() => onAdd(candidate)} className={btn("primary")}>
              <FiPlus className="h-3.5 w-3.5" aria-hidden />
              В витрину
            </button>
          ) : (
            // Сервер ставит в витрину только работы сотрудников: в адресе файла виден номер аккаунта автора.
            <span className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs text-muted-2">
              <FiLock className="h-3.5 w-3.5 shrink-0" aria-hidden />
              Работа пользователя — в витрину пока ставятся только работы сотрудников
            </span>
          )}
        </div>
      </div>
    </li>
  );
}
