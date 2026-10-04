"use client";

import { Fragment, useEffect, useState } from "react";
import { adminEditLevel, adminLevels, type AdminLevelChanges } from "@/lib/creators/adminApi";
import type { AdminLevel } from "@/lib/creators/adminTypes";
import { cmpDec, fmtPercent } from "@/lib/creators/format";
import type { CrError } from "@/lib/creators/types";
import {
  BTN_LG,
  BTN_PRIMARY,
  ErrorBox,
  INPUT,
  nf,
  OkBox,
  PageTitle,
  ROW,
  Skeleton,
  SuButton,
  SuCaption,
  TableWrap,
  TD,
  TH,
  THEAD_ROW,
} from "../_shared/ui";

type State = { levels: AdminLevel[] | null; error: CrError | null };

/**
 * Уровни программы: название, процент и пороги. Создавать, удалять и
 * переставлять уровни нельзя — только править условия. Пороги ничего не
 * включают сами: это подсказка «условия выполнены», уровень назначают вручную.
 */
export default function AdminCreatorsLevelsPage() {
  const [state, setState] = useState<State>({ levels: null, error: null });
  const [editing, setEditing] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      const res = await adminLevels();
      if (!alive) return;
      setState(res.ok ? { levels: res.data.results || [], error: null } : { levels: [], error: res.error });
    })();
    return () => {
      alive = false;
    };
  }, []);

  const levels = state.levels;

  return (
    <div className="space-y-4">
      <PageTitle title="Уровни" />
      <ul className="list-disc space-y-1 pl-5 text-sm text-muted">
        <li>Пороги только показываются креатору: повышение всегда вручную.</li>
        <li>Новый процент действует только для будущих комиссий.</li>
      </ul>

      <ErrorBox error={state.error} />
      <OkBox>{saved}</OkBox>

      {levels === null ? (
        <Skeleton />
      ) : (
        <TableWrap minWidth={860}>
          <thead>
            <tr className={THEAD_ROW}>
              <th className={TH}>Ключ</th>
              <th className={TH}>Название</th>
              <th className={TH}>Процент</th>
              <th className={TH}>Публикации</th>
              <th className={TH}>Регистрации</th>
              <th className={TH}>Платящие</th>
              <th className={TH}>Креаторов</th>
              <th className={TH} />
            </tr>
          </thead>
          <tbody>
            {levels.map((level) => (
              <Fragment key={level.key}>
                <tr className={`${ROW} hover:bg-surface-2`}>
                  <td className={`${TD} font-mono text-xs text-muted`}>{level.key}</td>
                  <td className={`${TD} font-medium`}>{level.title}</td>
                  <td className={`${TD} whitespace-nowrap`}>{fmtPercent(level.percent)}%</td>
                  <td className={TD}>{nf(level.min_publications)}</td>
                  <td className={TD}>{nf(level.min_registrations)}</td>
                  <td className={TD}>{nf(level.min_paying)}</td>
                  <td className={TD}>{nf(level.creators)}</td>
                  <td className={`${TD} text-right`}>
                    <SuButton
                      onClick={() => {
                        setSaved(null);
                        setEditing(editing === level.key ? null : level.key);
                      }}
                    >
                      {editing === level.key ? "Свернуть" : "Изменить"}
                    </SuButton>
                    <SuCaption className="mt-1" />
                  </td>
                </tr>
                {editing === level.key && (
                  <tr className={ROW}>
                    <td colSpan={8} className="bg-surface-2/50 px-4 py-4">
                      <LevelForm
                        level={level}
                        onCancel={() => setEditing(null)}
                        onSaved={(fresh) => {
                          setState((prev) => ({
                            ...prev,
                            levels: (prev.levels || []).map((item) => (item.key === fresh.key ? fresh : item)),
                          }));
                          setEditing(null);
                          setSaved(`Уровень ${fresh.title} сохранён.`);
                        }}
                      />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </TableWrap>
      )}
    </div>
  );
}

const INT_RE = /^\d{1,9}$/;
const PERCENT_RE = /^\d{1,2}(\.\d{1,2})?$/;

function LevelForm({
  level,
  onCancel,
  onSaved,
}: {
  level: AdminLevel;
  onCancel: () => void;
  onSaved: (level: AdminLevel) => void;
}) {
  const [title, setTitle] = useState(level.title);
  const [percent, setPercent] = useState(fmtPercent(level.percent));
  const [publications, setPublications] = useState(String(level.min_publications));
  const [registrations, setRegistrations] = useState(String(level.min_registrations));
  const [paying, setPaying] = useState(String(level.min_paying));
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<CrError | string | null>(null);

  const save = async () => {
    const pct = percent.trim().replace(",", ".");
    const cleanTitle = title.trim();
    if (!cleanTitle || cleanTitle.length > 64) return setError("Название: от 1 до 64 символов");
    if (!PERCENT_RE.test(pct) || cmpDec(pct, "0") <= 0 || cmpDec(pct, "25") > 0) {
      return setError("Процент комиссии должен быть больше 0 и не больше 25");
    }
    const ints = [publications, registrations, paying].map((value) => value.trim());
    if (!ints.every((value) => INT_RE.test(value))) return setError("Пороги — целые числа от 0");

    // Шлём только то, что изменилось: в журнал попадает ровно правка.
    const changes: AdminLevelChanges = {};
    if (cleanTitle !== level.title) changes.title = cleanTitle;
    if (cmpDec(pct, level.percent) !== 0) changes.percent = pct;
    if (Number(ints[0]) !== level.min_publications) changes.min_publications = Number(ints[0]);
    if (Number(ints[1]) !== level.min_registrations) changes.min_registrations = Number(ints[1]);
    if (Number(ints[2]) !== level.min_paying) changes.min_paying = Number(ints[2]);
    if (Object.keys(changes).length === 0) return setError("Нечего менять: значения те же");

    const note = changes.percent
      ? `\nПроцент ${fmtPercent(level.percent)}% → ${fmtPercent(changes.percent as string)}% — только для будущих комиссий.`
      : "";
    if (!confirm(`Сохранить изменения уровня ${level.title}?${note}`)) return;

    if (reason.trim()) changes.reason = reason.trim();
    setBusy(true);
    setError(null);
    const res = await adminEditLevel(level.key, changes);
    setBusy(false);
    if (res.ok) onSaved(res.data);
    else setError(res.error);
  };

  const field = "block text-xs text-muted";

  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        save();
      }}
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <label className={field}>
          Название
          <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={64} className={`${INPUT} mt-1 w-full`} />
        </label>
        <label className={field}>
          Процент комиссии, %
          <input
            value={percent}
            onChange={(e) => setPercent(e.target.value)}
            inputMode="decimal"
            className={`${INPUT} mt-1 w-full`}
          />
        </label>
        <label className={field}>
          Публикации, от
          <input
            value={publications}
            onChange={(e) => setPublications(e.target.value)}
            inputMode="numeric"
            className={`${INPUT} mt-1 w-full`}
          />
        </label>
        <label className={field}>
          Регистрации, от
          <input
            value={registrations}
            onChange={(e) => setRegistrations(e.target.value)}
            inputMode="numeric"
            className={`${INPUT} mt-1 w-full`}
          />
        </label>
        <label className={field}>
          Платящие, от
          <input value={paying} onChange={(e) => setPaying(e.target.value)} inputMode="numeric" className={`${INPUT} mt-1 w-full`} />
        </label>
      </div>
      <label className={field}>
        Причина (необязательно) — попадёт в журнал
        <input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} className={`${INPUT} mt-1 w-full`} />
      </label>
      <ErrorBox error={error} />
      <div className="flex flex-wrap gap-2">
        <button type="submit" disabled={busy} className={BTN_PRIMARY}>
          {busy ? "Сохраняю…" : "Сохранить"}
        </button>
        <button type="button" onClick={onCancel} disabled={busy} className={BTN_LG}>
          Отмена
        </button>
      </div>
    </form>
  );
}
