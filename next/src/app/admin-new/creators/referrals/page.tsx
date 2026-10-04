"use client";

import { useRef, useState } from "react";
import Money from "@/components/creators/shared/Money";
import { adminClearSuspect, adminRebind, adminReferrals } from "@/lib/creators/adminApi";
import type { AdminReferral } from "@/lib/creators/adminTypes";
import { SOURCE_RU } from "@/lib/creators/labels";
import type { CrError } from "@/lib/creators/types";
import { END_REASON, SUSPECT_REASON, labelFrom } from "../_shared/labels";
import ReasonDialog from "../_shared/ReasonDialog";
import { useCreatorsRole } from "../_shared/role";
import {
  Badge,
  BTN_PRIMARY,
  CARD,
  CreatorLink,
  dt,
  EmptyRow,
  ErrorBox,
  IdParamChip,
  INPUT,
  isDigits,
  MoreButton,
  nf,
  OkBox,
  PageTitle,
  ROW,
  SearchForm,
  Skeleton,
  SuButton,
  SuCaption,
  TableWrap,
  TD,
  TH,
  THEAD_ROW,
  ToggleChip,
  useIdParam,
} from "../_shared/ui";
import { usePagedList } from "../_shared/usePagedList";

/** Привязки пользователей к креаторам. Перепривязка — только вручную и только главным администратором. */
export default function AdminCreatorsReferralsPage() {
  const creator = useIdParam("creator");
  const [suspect, setSuspect] = useState(false);
  const [active, setActive] = useState(false);
  const [q, setQ] = useState("");
  const [clearing, setClearing] = useState<AdminReferral | null>(null);
  const [releaseHeld, setReleaseHeld] = useState(false);
  // Кого подставить в форму перепривязки (кнопка «Перепривязать…» в строке).
  const [prefill, setPrefill] = useState<{ userId: number; seq: number } | null>(null);
  const formRef = useRef<HTMLDivElement | null>(null);

  const list = usePagedList(adminReferrals, { creator, q, suspect, active });

  return (
    <div className="space-y-4">
      <PageTitle title="Рефералы" hint={`Кто за каким креатором закреплён. Найдено: ${nf(list.count)}.`} />

      <div ref={formRef}>
        <RebindForm key={prefill ? prefill.seq : 0} initialUserId={prefill ? String(prefill.userId) : ""} onDone={list.reload} />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <ToggleChip on={suspect} onChange={setSuspect}>
          Подозрительные
        </ToggleChip>
        <ToggleChip on={active} onChange={setActive}>
          Только действующие
        </ToggleChip>
        <IdParamChip name="creator" label="Creator" />
        <SearchForm placeholder="Email, username, промокод или id" onSearch={setQ} />
      </div>

      {list.loading ? (
        <Skeleton />
      ) : list.error ? (
        <ErrorBox error={list.error} />
      ) : (
        <TableWrap minWidth={1320}>
          <thead>
            <tr className={THEAD_ROW}>
              <th className={TH}>Пользователь</th>
              <th className={TH}>Creator</th>
              <th className={TH}>Источник</th>
              <th className={TH}>Привязан</th>
              <th className={TH}>Окончание</th>
              <th className={TH}>Проверка</th>
              <th className={TH}>Платит</th>
              <th className={TH}>Заказы</th>
              <th className={TH}>Продажи</th>
              <th className={TH}>Комиссия</th>
              <th className={TH}>Действия</th>
            </tr>
          </thead>
          <tbody>
            {list.rows.length === 0 && <EmptyRow colSpan={11}>Привязок нет.</EmptyRow>}
            {list.rows.map((row) => (
              <tr key={row.id} className={`${ROW} hover:bg-surface-2 ${row.suspect ? "bg-status-wait/5" : ""}`}>
                <td className={TD}>
                  <div className="break-all">{row.email || row.user_label}</div>
                  <div className="text-xs text-muted-2">id {row.user_id}</div>
                  {row.referred_by_id ? (
                    <div className="mt-1">
                      <Badge title={`Обычный реферер: пользователь id ${row.referred_by_id}`}>есть обычный реферер</Badge>
                    </div>
                  ) : null}
                </td>
                <td className={TD}>
                  <CreatorLink id={row.creator_id} name={row.creator_name} />
                </td>
                <td className={TD}>
                  <div className="whitespace-nowrap">{labelFrom(SOURCE_RU, row.source)}</div>
                  {row.code_used && <div className="font-mono text-xs text-muted-2">{row.code_used}</div>}
                </td>
                <td className={TD}>
                  <div className="whitespace-nowrap text-muted">{dt(row.bound_at)}</div>
                  {row.bound_by_email && <div className="break-all text-xs text-muted-2">вручную: {row.bound_by_email}</div>}
                </td>
                <td className={TD}>
                  {row.ended_at ? (
                    <>
                      <div className="whitespace-nowrap text-muted">{dt(row.ended_at)}</div>
                      <div className="text-xs text-muted-2">{labelFrom(END_REASON, row.end_reason) || "—"}</div>
                    </>
                  ) : (
                    <Badge tone="ok">действует</Badge>
                  )}
                </td>
                <td className={`${TD} max-w-[220px]`}>
                  {row.suspect ? (
                    <>
                      <Badge tone="wait">подозрительная</Badge>
                      <ul className="mt-1 space-y-0.5 text-xs text-muted">
                        {(row.flags?.reasons || []).map((reason) => (
                          <li key={reason}>{labelFrom(SUSPECT_REASON, reason)}</li>
                        ))}
                      </ul>
                    </>
                  ) : row.flags?.cleared_by ? (
                    <span className="text-xs text-muted-2">пометка снята</span>
                  ) : (
                    <span className="text-muted-2">—</span>
                  )}
                </td>
                <td className={TD}>{row.is_paying ? <span className="text-status-ok">✓</span> : "—"}</td>
                <td className={`${TD} whitespace-nowrap`}>{nf(row.orders)}</td>
                <td className={TD}>
                  <Money value={row.sales_usdt} />
                </td>
                <td className={TD}>
                  <Money value={row.commission_usdt} />
                </td>
                <td className={TD}>
                  <div className="flex flex-col items-start gap-1.5">
                    {row.suspect && (
                      <SuButton
                        onClick={() => {
                          setReleaseHeld(false);
                          setClearing(row);
                        }}
                      >
                        Снять пометку
                      </SuButton>
                    )}
                    <SuButton
                      onClick={() => {
                        setPrefill((prev) => ({ userId: row.user_id, seq: (prev?.seq ?? 0) + 1 }));
                        formRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
                      }}
                    >
                      Перепривязать…
                    </SuButton>
                    <SuCaption />
                  </div>
                </td>
              </tr>
            ))}
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

      {clearing && (
        <ReasonDialog
          title="Снять пометку «подозрительная»"
          description={`${clearing.email || clearing.user_label} (id ${clearing.user_id}) → ${clearing.creator_name}. Реферал снова будет считаться в статистике.`}
          reason="required"
          confirmLabel="Снять пометку"
          onClose={() => setClearing(null)}
          onSubmit={async (reason) => {
            const res = await adminClearSuspect(clearing.id, { reason, release_held: releaseHeld });
            if (!res.ok) return res.error;
            list.replace(res.data);
            return null;
          }}
        >
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              checked={releaseHeld}
              onChange={(e) => setReleaseHeld(e.target.checked)}
              className="mt-0.5 accent-accent"
            />
            <span>
              Выпустить придержанные комиссии
              <span className="block text-xs text-muted-2">
                Комиссии, придержанные из-за этой пометки, станут начисленными.
              </span>
            </span>
          </label>
        </ReasonDialog>
      )}
    </div>
  );
}

/** Форма «Перепривязать пользователя». Пустой креатор — снять привязку. */
function RebindForm({ initialUserId, onDone }: { initialUserId: string; onDone: () => void }) {
  const { isSuperuser } = useCreatorsRole();
  const [userId, setUserId] = useState(initialUserId);
  const [creatorId, setCreatorId] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<CrError | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const user = userId.trim();
  const creator = creatorId.trim();
  const valid = isDigits(user) && (creator === "" || isDigits(creator)) && reason.trim().length > 0;

  const submit = async () => {
    if (!valid || busy || !isSuperuser) return;
    const question = creator
      ? `Закрепить пользователя id ${user} за креатором #${creator}?`
      : `Снять привязку пользователя id ${user} к креатору?`;
    if (!confirm(`${question}\nМеняются только будущие оплаты.`)) return;
    setBusy(true);
    setError(null);
    setDone(null);
    const res = await adminRebind({
      user_id: Number(user),
      creator_id: creator ? Number(creator) : null,
      reason: reason.trim(),
    });
    setBusy(false);
    if (!res.ok) {
      setError(res.error);
      return;
    }
    const referral = res.data.referral;
    setDone(
      referral
        ? `Готово: пользователь id ${referral.user_id} закреплён за креатором ${referral.creator_name}.`
        : `Готово: привязка пользователя id ${user} снята.`,
    );
    setReason("");
    onDone();
  };

  return (
    <div className={`${CARD} space-y-3`}>
      <div>
        <h3 className="text-sm font-semibold">Перепривязать пользователя</h3>
        <p className="mt-1 text-xs text-muted">
          Меняет только будущие оплаты: уже начисленные комиссии остаются прежнему креатору. Поле «Creator» пустое —
          снять привязку.
        </p>
      </div>
      <form
        className="grid grid-cols-1 gap-3 sm:grid-cols-[160px_160px_1fr_auto] sm:items-end"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <label className="block text-xs text-muted">
          ID пользователя *
          <input
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
            inputMode="numeric"
            placeholder="например 1024"
            disabled={!isSuperuser}
            className={`${INPUT} mt-1 w-full`}
          />
        </label>
        <label className="block text-xs text-muted">
          ID креатора
          <input
            value={creatorId}
            onChange={(e) => setCreatorId(e.target.value)}
            inputMode="numeric"
            placeholder="пусто — снять"
            disabled={!isSuperuser}
            className={`${INPUT} mt-1 w-full`}
          />
        </label>
        <label className="block text-xs text-muted">
          Причина *
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            maxLength={500}
            disabled={!isSuperuser}
            className={`${INPUT} mt-1 w-full`}
          />
        </label>
        <button
          type="submit"
          disabled={!isSuperuser || !valid || busy}
          title={isSuperuser ? undefined : "Только главный администратор"}
          className={BTN_PRIMARY}
        >
          {busy ? "Сохраняю…" : creator ? "Перепривязать" : "Снять привязку"}
        </button>
      </form>
      <SuCaption />
      <p className="text-[11px] text-muted-2">
        ID креатора — номер в адресе его профиля (/admin-new/creators/<span className="font-mono">12</span>), ID
        пользователя — в столбце «Пользователь» ниже или в разделе «Пользователи» панели.
      </p>
      <ErrorBox error={error} />
      <OkBox>{done}</OkBox>
    </div>
  );
}
