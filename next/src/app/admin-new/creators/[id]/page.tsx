"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import Money from "@/components/creators/shared/Money";
import { adminCreator } from "@/lib/creators/adminApi";
import type { AdminCreatorProfile } from "@/lib/creators/adminTypes";
import { cmpDec, fmtPercent } from "@/lib/creators/format";
import { CREDIT_CATEGORY_RU, NETWORK_RU, SOURCE_RU } from "@/lib/creators/labels";
import type { CrError, Part } from "@/lib/creators/types";
import LogChanges from "../_shared/LogChanges";
import { CREATOR_STATUS, LANG, PUBLICATION_STATUS, labelFrom, logActionLabel } from "../_shared/labels";
import ProfileActions from "../_shared/ProfileActions";
import PublicationActions from "../_shared/PublicationActions";
import WithdrawalRow, { WITHDRAWAL_COLUMNS } from "../_shared/WithdrawalRow";
import {
  Badge,
  CARD,
  CopyButton,
  d,
  dash,
  dt,
  EmptyRow,
  ErrorBox,
  ExtLink,
  isDigits,
  nf,
  OkBox,
  ROW,
  Skeleton,
  StatusPill,
  TableWrap,
  TD,
  TH,
  THEAD_ROW,
} from "../_shared/ui";
import { useLevels } from "../_shared/useLevels";

type State = { id: string | null; profile: AdminCreatorProfile | null; error: CrError | null };

/** Профиль креатора (ТЗ п.31–32): кто это, цифры, деньги, риск, история и действия. */
export default function AdminCreatorProfilePage() {
  const params = useParams<{ id: string }>();
  const id = String(params?.id ?? "");
  const [state, setState] = useState<State>({ id: null, profile: null, error: null });
  const [tick, setTick] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const { levels } = useLevels();

  // Не число в адресе — такого креатора нет, сервер не спрашиваем.
  const valid = isDigits(id);

  useEffect(() => {
    if (!valid) return;
    let alive = true;
    (async () => {
      const res = await adminCreator(id);
      if (!alive) return;
      setState(res.ok ? { id, profile: res.data, error: null } : { id, profile: null, error: res.error });
    })();
    return () => {
      alive = false;
    };
  }, [id, tick, valid]);

  // После любого действия профиль перечитывается целиком: меняются и баланс, и риск, и журнал.
  const reload = useCallback(() => setTick((value) => value + 1), []);

  const back = (
    <Link href="/admin-new/creators/list" className="text-sm text-muted hover:text-accent">
      ← Все Creators
    </Link>
  );

  if (!valid) {
    return (
      <div className="space-y-4">
        {back}
        <ErrorBox error="Креатор не найден." />
      </div>
    );
  }

  if (state.id !== id) return <Skeleton className="h-[480px]" />;

  if (!state.profile) {
    return (
      <div className="space-y-4">
        {back}
        <ErrorBox error={state.error?.code === "not_found" ? "Креатор не найден." : state.error} />
      </div>
    );
  }

  const profile = state.profile;
  const { creator, application, counters, money, progress, risk, credits } = profile;
  const all = (tab: string) => `/admin-new/creators/${tab}?creator=${creator.id}`;
  const socials = application
    ? [application.instagram_url, application.tiktok_url, application.youtube_url, ...(application.other_links || [])].filter(Boolean)
    : [];
  const hasDebt = cmpDec(risk.debt, "0") > 0;

  return (
    <div className="space-y-5">
      {back}

      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h2 className="min-w-0 break-words text-xl font-semibold">{creator.display_name}</h2>
        <StatusPill table={CREATOR_STATUS} status={creator.status} />
        <Badge>
          {creator.level.title} · {fmtPercent(creator.percent)}%
        </Badge>
        {progress.conditions_met && (
          <Badge tone="wait" title="Пороги следующего уровня достигнуты. Повышение — только вручную.">
            условия уровня выполнены
          </Badge>
        )}
      </div>

      {creator.status === "blocked" && (
        <ErrorBox
          error={`Креатор заблокирован${creator.blocked_at ? ` ${dt(creator.blocked_at)}` : ""}${
            creator.blocked_reason ? `. Причина: ${creator.blocked_reason}` : ""
          }`}
        />
      )}
      <OkBox>{notice}</OkBox>

      <Section title="Действия">
        <ProfileActions
          profile={profile}
          levels={levels}
          onChanged={(message) => {
            setNotice(message);
            reload();
          }}
        />
      </Section>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <Section title="Основная информация">
          <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
            <Info label="Email">{dash(creator.email)}</Info>
            <Info label="Username">{dash(creator.username)}</Info>
            <Info label="Telegram">{dash(creator.telegram)}</Info>
            <Info label="В программе с">{d(creator.joined_at)}</Info>
            <Info label="Уровень">
              {creator.level.title} — {fmtPercent(creator.percent)}%
            </Info>
            <Info label="Язык уведомлений">{labelFrom(LANG, creator.lang)}</Info>
            <Info label="ID">
              креатор #{creator.id} · пользователь id {creator.user_id}
            </Info>
            <Info label="Промокоды">
              {profile.codes.length === 0 ? (
                <span className="text-muted-2">промокод не создан</span>
              ) : (
                <ul className="space-y-1">
                  {profile.codes.map((item) => (
                    <li key={item.code} className="flex flex-wrap items-center gap-2">
                      <span className="font-mono">{item.code}</span>
                      <Badge tone={item.is_primary ? "ok" : "muted"}>
                        {item.is_primary ? "основной" : item.is_active ? "псевдоним" : "отключён"}
                      </Badge>
                    </li>
                  ))}
                </ul>
              )}
            </Info>
            <Info label="Соцсети из заявки" wide>
              {socials.length === 0 ? (
                <span className="text-muted-2">—</span>
              ) : (
                <ul className="space-y-1">
                  {socials.map((url, index) => (
                    <li key={`${index}-${url}`}>
                      <ExtLink href={url} />
                    </li>
                  ))}
                </ul>
              )}
            </Info>
            <Info label="Адрес выплат (USDT TRC20)" wide>
              {creator.payout_address ? (
                <div className="flex flex-wrap items-center gap-2">
                  <span className="break-all font-mono text-xs">{creator.payout_address}</span>
                  <CopyButton text={creator.payout_address} />
                </div>
              ) : (
                <span className="text-muted-2">не указан</span>
              )}
              {creator.payout_address_changed_at && (
                <div className="mt-1 text-xs text-muted-2">изменён {dt(creator.payout_address_changed_at)}</div>
              )}
            </Info>
          </dl>
        </Section>

        <Section title="Статистика">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <Tile label="Переходы">{nf(counters.clicks)}</Tile>
            <Tile label="Регистрации">{nf(counters.registrations)}</Tile>
            <Tile label="Платящие">{nf(counters.paying)}</Tile>
            <Tile label="Заказы">{nf(counters.orders)}</Tile>
            <Tile label="Продажи">
              <Money value={counters.sales_usdt} />
            </Tile>
            <Tile label="Публикаций подтверждено">{nf(counters.publications_approved)}</Tile>
          </div>

          <h4 className="mt-5 text-xs uppercase tracking-wide text-muted-2">Деньги</h4>
          <div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-3">
            <Tile label="Заработано всего">
              <Money value={money.earned} />
            </Tile>
            {/* pending с сервера — это холд плюс открытые заявки на вывод, а не один холд. */}
            <Tile label="Ожидает выплаты" title="Комиссии в холде плюс открытые заявки на вывод">
              <Money value={money.pending} />
            </Tile>
            <Tile label="На проверке">
              <Money value={money.held} />
            </Tile>
            <Tile label="Доступно к выводу">
              <Money value={money.available} />
            </Tile>
            <Tile label="В заявках на вывод">
              <Money value={money.in_withdrawal} />
            </Tile>
            <Tile label="Выплачено">
              <Money value={money.paid} />
            </Tile>
          </div>

          <h4 className="mt-5 text-xs uppercase tracking-wide text-muted-2">
            До следующего уровня{progress.next_level ? `: ${progress.next_level.title} — ${fmtPercent(progress.next_level.percent)}%` : ""}
          </h4>
          {progress.next_level ? (
            <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-3">
              <ProgressTile label="Публикации" part={progress.publications} />
              <ProgressTile label="Регистрации" part={progress.registrations} />
              <ProgressTile label="Платящие" part={progress.paying} />
            </div>
          ) : (
            <p className="mt-2 text-sm text-muted">Максимальный уровень.</p>
          )}
          {progress.conditions_met && (
            <p className="mt-2 text-xs text-status-wait">
              Условия выполнены. Это подсказка: уровень меняет только главный администратор кнопкой «Изменить уровень».
            </p>
          )}

          <h4 className="mt-5 text-xs uppercase tracking-wide text-muted-2">Риск</h4>
          <div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Tile label="Подозрительные рефералы" alarm={risk.suspect_referrals > 0}>
              {nf(risk.suspect_referrals)}
            </Tile>
            <Tile label="Придержанные комиссии" alarm={risk.held_commissions > 0}>
              {nf(risk.held_commissions)}
            </Tile>
            <Tile label="Отменённые возвратом" alarm={risk.reversed_commissions > 0}>
              {nf(risk.reversed_commissions)}
            </Tile>
            <Tile label="Долг" alarm={hasDebt}>
              <Money value={risk.debt} />
            </Tile>
          </div>
        </Section>
      </div>

      <Section title="Публикации" hint="последние 50" allHref={all("publications")}>
        <TableWrap minWidth={760}>
          <thead>
            <tr className={THEAD_ROW}>
              <th className={TH}>Дата</th>
              <th className={TH}>Соцсеть</th>
              <th className={TH}>Ссылка</th>
              <th className={TH}>Описание</th>
              <th className={TH}>Статус</th>
              <th className={TH}>Действия</th>
            </tr>
          </thead>
          <tbody>
            {profile.publications.length === 0 && <EmptyRow colSpan={6}>Публикаций нет.</EmptyRow>}
            {profile.publications.map((row) => (
              <tr key={row.id} className={ROW}>
                <td className={`${TD} whitespace-nowrap text-muted`}>{dt(row.created_at)}</td>
                <td className={`${TD} whitespace-nowrap`}>{labelFrom(NETWORK_RU, row.network)}</td>
                <td className={`${TD} max-w-[240px]`}>
                  <ExtLink href={row.url}>Открыть</ExtLink>
                  <div className="mt-0.5 break-all text-xs text-muted-2">{row.url}</div>
                </td>
                <td className={`${TD} max-w-[220px] whitespace-pre-wrap break-words text-muted`}>{dash(row.description)}</td>
                <td className={TD}>
                  <StatusPill table={PUBLICATION_STATUS} status={row.status} />
                  {row.reject_reason && (
                    <div className="mt-1 max-w-[200px] break-words text-xs text-rose-300">Причина: {row.reject_reason}</div>
                  )}
                </td>
                <td className={TD}>
                  <PublicationActions row={row} onChange={reload} />
                </td>
              </tr>
            ))}
          </tbody>
        </TableWrap>
      </Section>

      <Section title="Рефералы" hint="последние 50" allHref={all("referrals")}>
        <TableWrap minWidth={820}>
          <thead>
            <tr className={THEAD_ROW}>
              <th className={TH}>Пользователь</th>
              <th className={TH}>Привязан</th>
              <th className={TH}>Источник</th>
              <th className={TH}>Состояние</th>
              <th className={TH}>Заказы</th>
              <th className={TH}>Продажи</th>
              <th className={TH}>Комиссия</th>
            </tr>
          </thead>
          <tbody>
            {profile.referrals.length === 0 && <EmptyRow colSpan={7}>Рефералов нет.</EmptyRow>}
            {profile.referrals.map((row) => (
              <tr key={row.id} className={`${ROW} ${row.suspect ? "bg-status-wait/5" : ""}`}>
                <td className={TD}>
                  <div className="break-all">{row.email || row.user_label}</div>
                  <div className="text-xs text-muted-2">id {row.user_id}</div>
                </td>
                <td className={`${TD} whitespace-nowrap text-muted`}>{dt(row.bound_at)}</td>
                <td className={TD}>
                  {labelFrom(SOURCE_RU, row.source)}
                  {row.code_used && <div className="font-mono text-xs text-muted-2">{row.code_used}</div>}
                </td>
                <td className={TD}>
                  <div className="flex flex-wrap gap-1">
                    {row.ended_at ? <Badge>закончилась {d(row.ended_at)}</Badge> : <Badge tone="ok">действует</Badge>}
                    {row.suspect && <Badge tone="wait">подозрительная</Badge>}
                    {row.is_paying && <Badge tone="ok">платит</Badge>}
                  </div>
                </td>
                <td className={`${TD} whitespace-nowrap`}>{nf(row.orders)}</td>
                <td className={TD}>
                  <Money value={row.sales_usdt} />
                </td>
                <td className={TD}>
                  <Money value={row.commission_usdt} />
                </td>
              </tr>
            ))}
          </tbody>
        </TableWrap>
        <p className="mt-2 text-xs text-muted-2">
          Снять пометку и перепривязать пользователя — во вкладке «Рефералы». Комиссии этого креатора —{" "}
          <Link href={all("commissions")} className="text-accent hover:underline">
            во вкладке «Комиссии»
          </Link>
          .
        </p>
      </Section>

      <Section title="Creator Credits" hint="последние 100 операций" allHref={all("credits")}>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Tile label="Выдано">{nf(credits.granted)}</Tile>
          <Tile label="Осталось">{nf(credits.remaining)}</Tile>
          <Tile label="Использовано">{nf(credits.spent)}</Tile>
          <Tile label="Общий баланс кошелька">{nf(credits.wallet_balance)}</Tile>
        </div>
        <div className="mt-3">
          <TableWrap minWidth={720}>
            <thead>
              <tr className={THEAD_ROW}>
                <th className={TH}>Дата</th>
                <th className={TH}>Количество</th>
                <th className={TH}>Причина</th>
                <th className={TH}>Примечание</th>
                <th className={TH}>Кто выдал</th>
                <th className={TH}>Остаток Creator Credits</th>
              </tr>
            </thead>
            <tbody>
              {credits.history.length === 0 && <EmptyRow colSpan={6}>Начислений и расходов нет.</EmptyRow>}
              {credits.history.map((row) => {
                const spend = row.kind === "spend";
                return (
                  <tr key={`${row.kind || "grant"}-${row.id}`} className={ROW}>
                    <td className={`${TD} whitespace-nowrap text-muted`}>{dt(row.date)}</td>
                    <td className={`${TD} whitespace-nowrap font-medium ${spend ? "text-muted" : "text-status-ok"}`}>
                      {spend ? nf(row.amount) : `+${nf(row.amount)}`}
                    </td>
                    <td className={TD}>
                      {spend
                        ? `Расход: ${dash(row.reason_label)}`
                        : (CREDIT_CATEGORY_RU[row.category || ""] ?? dash(row.category_label))}
                    </td>
                    <td className={`${TD} max-w-[240px] whitespace-pre-wrap break-words text-muted`}>{dash(row.note)}</td>
                    <td className={`${TD} break-all`}>{spend ? "—" : dash(row.by_email)}</td>
                    <td className={`${TD} whitespace-nowrap`}>
                      {row.remaining_after === undefined ? "—" : nf(row.remaining_after)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </TableWrap>
        </div>
      </Section>

      <Section title="Выплаты" hint="последние 50" allHref={all("withdrawals")}>
        <TableWrap minWidth={1280}>
          <thead>
            <tr className={THEAD_ROW}>
              {WITHDRAWAL_COLUMNS.map((title) => (
                <th key={title} className={TH}>
                  {title}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {profile.withdrawals.length === 0 && <EmptyRow colSpan={WITHDRAWAL_COLUMNS.length}>Заявок на вывод нет.</EmptyRow>}
            {profile.withdrawals.map((row) => (
              <WithdrawalRow key={row.id} row={row} onChange={reload} />
            ))}
          </tbody>
        </TableWrap>
      </Section>

      <Section title="Журнал" hint="последние 20 действий" allHref={all("log")}>
        <TableWrap minWidth={860}>
          <thead>
            <tr className={THEAD_ROW}>
              <th className={TH}>Дата</th>
              <th className={TH}>Кто</th>
              <th className={TH}>Действие</th>
              <th className={TH}>Было → стало</th>
              <th className={TH}>Причина</th>
            </tr>
          </thead>
          <tbody>
            {profile.log.length === 0 && <EmptyRow colSpan={5}>Записей нет.</EmptyRow>}
            {profile.log.map((row) => (
              <tr key={row.id} className={ROW}>
                <td className={`${TD} whitespace-nowrap text-muted`}>{dt(row.created_at)}</td>
                <td className={`${TD} break-all`}>{row.actor_email || `id ${row.actor_id}`}</td>
                <td className={TD}>{logActionLabel(row.action)}</td>
                <td className={`${TD} max-w-[300px]`}>
                  <LogChanges before={row.before} after={row.after} />
                </td>
                <td className={`${TD} max-w-[240px] whitespace-pre-wrap break-words text-muted`}>{dash(row.reason)}</td>
              </tr>
            ))}
          </tbody>
        </TableWrap>
      </Section>
    </div>
  );
}

function Section({
  title,
  hint,
  allHref,
  children,
}: {
  title: string;
  hint?: string;
  allHref?: string;
  children: ReactNode;
}) {
  return (
    <section className={`${CARD} min-w-0`}>
      <div className="mb-4 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3 className="text-base font-semibold">{title}</h3>
        {hint && <span className="text-xs text-muted-2">{hint}</span>}
        {allHref && (
          <Link href={allHref} className="ml-auto text-sm text-accent hover:underline">
            Все →
          </Link>
        )}
      </div>
      {children}
    </section>
  );
}

function Info({ label, wide = false, children }: { label: string; wide?: boolean; children: ReactNode }) {
  return (
    <div className={`min-w-0 ${wide ? "sm:col-span-2" : ""}`}>
      <dt className="text-xs uppercase tracking-wide text-muted-2">{label}</dt>
      <dd className="mt-1 break-words text-sm">{children}</dd>
    </div>
  );
}

function Tile({
  label,
  title,
  alarm = false,
  children,
}: {
  label: string;
  title?: string;
  alarm?: boolean;
  children: ReactNode;
}) {
  return (
    <div
      title={title}
      className={`min-w-0 rounded-xl border px-3 py-2.5 ${
        alarm ? "border-status-fail/40 bg-status-fail/10" : "border-border bg-surface-2"
      }`}
    >
      <div className="text-[11px] leading-tight text-muted-2">{label}</div>
      <div className={`mt-1 break-words text-sm font-semibold tabular-nums ${alarm ? "text-status-fail" : ""}`}>{children}</div>
    </div>
  );
}

function ProgressTile({ label, part }: { label: string; part: Part }) {
  return (
    <Tile label={label}>
      {nf(part.have)} / {nf(part.need)}
      {part.done ? <span className="ml-1 text-status-ok">✓</span> : null}
    </Tile>
  );
}
