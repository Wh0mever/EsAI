"use client";

import { Fragment, useState } from "react";
import Link from "next/link";
import {
  adminApplications,
  adminApproveApplication,
  adminRejectApplication,
  adminUnblockApplication,
} from "@/lib/creators/adminApi";
import type { AdminApplication, AdminCreatorRow, AdminLevel } from "@/lib/creators/adminTypes";
import { fmtPercent } from "@/lib/creators/format";
import type { ApplicationStatus, CrError } from "@/lib/creators/types";
import { APPLICATION_STATUS, LANG, SU_ONLY, labelFrom } from "./_shared/labels";
import ReasonDialog from "./_shared/ReasonDialog";
import { useCreatorsRole } from "./_shared/role";
import {
  BTN,
  BTN_DANGER_MD,
  BTN_MD,
  BTN_OK_MD,
  Chips,
  dash,
  dt,
  EmptyRow,
  ErrorBox,
  errText,
  ExtLink,
  INPUT_SM,
  MoreButton,
  nf,
  OkBox,
  PageTitle,
  ROW,
  SearchForm,
  Skeleton,
  StatusPill,
  SuButton,
  SuCaption,
  TableWrap,
  TD,
  TH,
  THEAD_ROW,
} from "./_shared/ui";
import { BASE_LEVEL_KEY, useLevels } from "./_shared/useLevels";
import { usePagedList } from "./_shared/usePagedList";

type Filter = ApplicationStatus | "all";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "Все" },
  { key: "new", label: "Новые" },
  { key: "approved", label: "Одобренные" },
  { key: "rejected", label: "Отклонённые" },
  { key: "blocked", label: "Заблокированные" },
];

type Approved = { application: AdminApplication; creator: AdminCreatorRow };

/** Заявки на участие (ТЗ п.7). Одобрение — только вручную и только с выбранным уровнем (ТЗ п.8). */
export default function AdminCreatorsApplicationsPage() {
  const [filter, setFilter] = useState<Filter>("new");
  const [q, setQ] = useState("");
  const [openId, setOpenId] = useState<number | null>(null);
  const [approved, setApproved] = useState<Approved | null>(null);
  const { levels, error: levelsError } = useLevels();

  const list = usePagedList(adminApplications, { status: filter === "all" ? undefined : filter, q });

  return (
    <div className="space-y-4">
      <PageTitle
        title="Заявки"
        hint={`Каждую заявку проверяет человек: автоматического одобрения нет. Найдено: ${nf(list.count)}.`}
      />

      <div className="flex flex-wrap items-center gap-2">
        <Chips options={FILTERS} value={filter} onChange={setFilter} />
        <SearchForm placeholder="Имя, Telegram или email" onSearch={setQ} />
      </div>

      <ErrorBox error={levelsError} />
      {approved && (
        <OkBox>
          Заявка одобрена: {approved.application.name} — уровень {approved.creator.level.title}.{" "}
          <Link href={`/admin-new/creators/${approved.creator.id}`} className="underline">
            Открыть профиль
          </Link>
        </OkBox>
      )}

      {list.loading ? (
        <Skeleton />
      ) : list.error ? (
        <ErrorBox error={list.error} />
      ) : (
        <TableWrap minWidth={860}>
          <thead>
            <tr className={THEAD_ROW}>
              <th className={TH}>Дата</th>
              <th className={TH}>Заявитель</th>
              <th className={TH}>Telegram</th>
              <th className={TH}>Страна</th>
              <th className={TH}>Подписчики</th>
              <th className={TH}>Статус</th>
              <th className={TH} />
            </tr>
          </thead>
          <tbody>
            {list.rows.length === 0 && <EmptyRow colSpan={7}>Заявок нет.</EmptyRow>}
            {list.rows.map((row) => {
              const isOpen = openId === row.id;
              return (
                <Fragment key={row.id}>
                  <tr className={`${ROW} hover:bg-surface-2`}>
                    <td className={`${TD} whitespace-nowrap text-muted`}>{dt(row.created_at)}</td>
                    <td className={TD}>
                      <div className="font-medium">{row.name}</div>
                      <div className="break-all text-xs text-muted-2">{dash(row.email)}</div>
                    </td>
                    <td className={`${TD} break-all`}>{dash(row.telegram)}</td>
                    <td className={TD}>{dash(row.country)}</td>
                    <td className={`${TD} whitespace-nowrap`}>{nf(row.followers)}</td>
                    <td className={TD}>
                      <StatusPill table={APPLICATION_STATUS} status={row.status} />
                    </td>
                    <td className={`${TD} whitespace-nowrap text-right`}>
                      <button type="button" className={BTN} onClick={() => setOpenId(isOpen ? null : row.id)}>
                        {isOpen ? "Свернуть" : "Подробнее"}
                      </button>
                    </td>
                  </tr>
                  {isOpen && (
                    <tr className={ROW}>
                      <td colSpan={7} className="bg-surface-2/50 px-4 py-4">
                        <ApplicationDetails
                          row={row}
                          levels={levels}
                          onChange={list.replace}
                          onApproved={(result) => {
                            list.replace(result.application);
                            setApproved(result);
                          }}
                        />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </TableWrap>
      )}

      <MoreButton
        shown={list.rows.length}
        total={list.count}
        loading={list.loadingMore}
        onMore={list.more}
        error={list.moreError}
      />
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-xs uppercase tracking-wide text-muted-2">{label}</div>
      <div className="mt-1 whitespace-pre-wrap break-words text-sm">{children}</div>
    </div>
  );
}

function Links({ items }: { items: string[] }) {
  const links = items.filter(Boolean);
  if (links.length === 0) return <span className="text-muted-2">—</span>;
  return (
    <ul className="space-y-1">
      {links.map((url, index) => (
        <li key={`${index}-${url}`}>
          <ExtLink href={url} />
        </li>
      ))}
    </ul>
  );
}

function ApplicationDetails({
  row,
  levels,
  onChange,
  onApproved,
}: {
  row: AdminApplication;
  levels: AdminLevel[] | null;
  onChange: (row: AdminApplication) => void;
  onApproved: (result: Approved) => void;
}) {
  const { isSuperuser, role } = useCreatorsRole();
  // Уровень по умолчанию не выбран: администратор назначает его сам (ТЗ п.8).
  const [level, setLevel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<CrError | null>(null);
  const [dialog, setDialog] = useState<"reject" | "block" | "unblock" | null>(null);

  const approve = async () => {
    const chosen = levels?.find((item) => item.key === level);
    if (!chosen) return;
    if (!confirm(`Одобрить заявку «${row.name}» с уровнем ${chosen.title} (${fmtPercent(chosen.percent)}%)?`)) return;
    setBusy(true);
    setError(null);
    const res = await adminApproveApplication(row.id, level);
    setBusy(false);
    if (res.ok) onApproved(res.data);
    else setError(res.error);
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="Instagram">
          <ExtLink href={row.instagram_url} />
        </Field>
        <Field label="TikTok">
          <ExtLink href={row.tiktok_url} />
        </Field>
        <Field label="YouTube">
          <ExtLink href={row.youtube_url} />
        </Field>
        <Field label="Другие соцсети">
          <Links items={row.other_links || []} />
        </Field>
        <Field label="Примеры работ">
          <Links items={row.samples || []} />
        </Field>
        <Field label="Язык · пользователь · IP">
          {labelFrom(LANG, row.lang)} · id {row.user_id} · {dash(row.ip)}
        </Field>
        <Field label="Чем занимается">{dash(row.occupation)}</Field>
        <Field label="Зачем хочет участвовать">{dash(row.motivation)}</Field>
        <Field label="Решение">
          {row.decided_at ? (
            <>
              {labelFrom(APPLICATION_STATUS, row.status)} · {dt(row.decided_at)}
              <br />
              <span className="text-muted">Кто решил: {dash(row.decided_by_email)}</span>
              {row.reject_reason ? (
                <>
                  <br />
                  <span className="text-muted">Причина: {row.reject_reason}</span>
                </>
              ) : null}
            </>
          ) : (
            <span className="text-muted-2">ещё не принято</span>
          )}
        </Field>
      </div>

      {row.status === "new" && (
        <div className="space-y-2 border-t border-border pt-4">
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={level}
              onChange={(e) => setLevel(e.target.value)}
              disabled={!levels || busy}
              className={INPUT_SM}
              aria-label="Уровень"
            >
              <option value="" disabled>
                {levels ? "Выберите уровень" : "Уровни загружаются…"}
              </option>
              {(levels || []).map((item) => {
                const locked = !isSuperuser && item.key !== BASE_LEVEL_KEY;
                return (
                  <option key={item.key} value={item.key} disabled={locked}>
                    {item.title} — {fmtPercent(item.percent)}%{locked ? " (недоступно)" : ""}
                  </option>
                );
              })}
            </select>
            <button type="button" className={BTN_OK_MD} disabled={!level || busy} onClick={approve}>
              {busy ? "Одобряю…" : "Одобрить"}
            </button>
            <button type="button" className={BTN_DANGER_MD} disabled={busy} onClick={() => setDialog("reject")}>
              Отклонить
            </button>
            <SuButton className={BTN_DANGER_MD} disabled={busy} onClick={() => setDialog("block")}>
              Заблокировать
            </SuButton>
          </div>
          {role === "staff" && (
            <p className="text-[11px] text-muted-2">
              Уровень выше CREATOR и «Заблокировать» — {SU_ONLY.toLowerCase()}.
            </p>
          )}
          {error && <p className="text-sm text-rose-300">{errText(error)}</p>}
        </div>
      )}

      {row.status === "blocked" && (
        <div className="space-y-1 border-t border-border pt-4">
          <SuButton className={BTN_MD} onClick={() => setDialog("unblock")}>
            Разблокировать
          </SuButton>
          <SuCaption />
        </div>
      )}

      {dialog === "reject" && (
        <ReasonDialog
          title="Отклонить заявку"
          description={`${row.name}. Человек сможет подать заявку снова.`}
          reason="optional"
          reasonLabel="Причина — её увидит заявитель"
          confirmLabel="Отклонить"
          danger
          onClose={() => setDialog(null)}
          onSubmit={async (reason) => {
            const res = await adminRejectApplication(row.id, { reason, block: false });
            if (!res.ok) return res.error;
            onChange(res.data);
            return null;
          }}
        />
      )}

      {dialog === "block" && (
        <ReasonDialog
          title="Отклонить и заблокировать"
          description={`${row.name}. Заявка будет отклонена, подать новую человек не сможет.`}
          reason="optional"
          reasonLabel="Причина — её увидит заявитель"
          confirmLabel="Заблокировать"
          confirmText="Отклонить и запретить подавать заявку снова?"
          danger
          onClose={() => setDialog(null)}
          onSubmit={async (reason) => {
            const res = await adminRejectApplication(row.id, { reason, block: true });
            if (!res.ok) return res.error;
            onChange(res.data);
            return null;
          }}
        />
      )}

      {dialog === "unblock" && (
        <ReasonDialog
          title="Разблокировать подачу заявки"
          description={`${row.name}. Заявка станет «Отклонена», человек сможет подать новую.`}
          reason="required"
          confirmLabel="Разблокировать"
          onClose={() => setDialog(null)}
          onSubmit={async (reason) => {
            const res = await adminUnblockApplication(row.id, reason);
            if (!res.ok) return res.error;
            onChange(res.data);
            return null;
          }}
        />
      )}
    </div>
  );
}
