"use client";

import { useState } from "react";
import { adminBlock, adminChangeCode, adminGrantCredits, adminSetLevel, adminUnblock } from "@/lib/creators/adminApi";
import type { AdminCreatorProfile, AdminLevel } from "@/lib/creators/adminTypes";
import { fmtPercent, isCodeShape } from "@/lib/creators/format";
import { GRANT_CATEGORIES } from "./labels";
import ReasonDialog from "./ReasonDialog";
import { BTN, BTN_DANGER_MD, BTN_MD, BTN_OK_MD, BTN_ON, INPUT, nf, SuButton, SuCaption } from "./ui";

type Dialog = "level" | "block" | "unblock" | "code" | "credits" | null;

const CREDIT_PRESETS = [500, 1000, 2000, 5000];
const CREDIT_MAX = 1_000_000;
const NOTE_MAX = 300;

/**
 * Действия главного администратора в профиле креатора: уровень, блокировка,
 * промокод, Creator Credits. Всё — только вручную: ни уровень, ни кредиты
 * сами не меняются ни от каких показателей.
 */
export default function ProfileActions({
  profile,
  levels,
  onChanged,
}: {
  profile: AdminCreatorProfile;
  levels: AdminLevel[] | null;
  /** Действие выполнено: перечитать профиль и показать, что получилось. */
  onChanged: (message: string) => void;
}) {
  const creator = profile.creator;
  const [dialog, setDialog] = useState<Dialog>(null);
  const [level, setLevel] = useState("");
  const [code, setCode] = useState("");
  const [amount, setAmount] = useState("");
  const [category, setCategory] = useState("");
  const [note, setNote] = useState("");

  const open = (next: Dialog) => {
    // Каждое окно начинается пустым: ни уровня, ни причины начисления по умолчанию.
    setLevel("");
    setCode("");
    setAmount("");
    setCategory("");
    setNote("");
    setDialog(next);
  };
  const close = () => setDialog(null);

  const otherLevels = (levels || []).filter((item) => item.key !== creator.level.key);
  const chosenLevel = otherLevels.find((item) => item.key === level);

  const newCode = code.trim().toUpperCase();
  const codeOk = isCodeShape(newCode) && newCode !== (creator.code || "");

  const amountText = amount.trim();
  const amountValue = /^\d{1,7}$/.test(amountText) ? Number(amountText) : NaN;
  const amountOk = Number.isInteger(amountValue) && amountValue >= 1 && amountValue <= CREDIT_MAX;
  const categoryLabel = GRANT_CATEGORIES.find((item) => item.key === category)?.label;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <SuButton className={BTN_MD} onClick={() => open("level")}>
          Изменить уровень
        </SuButton>
        <SuButton className={BTN_MD} onClick={() => open("code")}>
          Изменить промокод
        </SuButton>
        <SuButton className={BTN_OK_MD} onClick={() => open("credits")}>
          Начислить Creator Credits
        </SuButton>
        {creator.status === "blocked" ? (
          <SuButton className={BTN_MD} onClick={() => open("unblock")}>
            Разблокировать
          </SuButton>
        ) : (
          <SuButton className={BTN_DANGER_MD} onClick={() => open("block")}>
            Заблокировать
          </SuButton>
        )}
      </div>
      <SuCaption />

      {dialog === "level" && (
        <ReasonDialog
          title="Изменить уровень"
          description={`${creator.display_name}. Сейчас: ${creator.level.title} — ${fmtPercent(creator.percent)}%.`}
          reason="optional"
          confirmLabel="Изменить уровень"
          canSubmit={Boolean(chosenLevel)}
          onClose={close}
          onSubmit={async (reason) => {
            const res = await adminSetLevel(creator.id, { level, reason });
            if (!res.ok) return res.error;
            onChanged(`Уровень изменён: ${res.data.level.title} — ${fmtPercent(res.data.percent)}%.`);
            return null;
          }}
        >
          <label className="block text-sm">
            <span className="text-muted">Новый уровень *</span>
            <select value={level} onChange={(e) => setLevel(e.target.value)} className={`${INPUT} mt-1.5 w-full`}>
              <option value="" disabled>
                {levels ? "Выберите уровень" : "Уровни загружаются…"}
              </option>
              {otherLevels.map((item) => (
                <option key={item.key} value={item.key}>
                  {item.title} — {fmtPercent(item.percent)}%
                </option>
              ))}
            </select>
            <span className="mt-1 block text-xs text-muted-2">Процент меняется только для будущих комиссий.</span>
          </label>
        </ReasonDialog>
      )}

      {dialog === "block" && (
        <ReasonDialog
          title="Заблокировать креатора"
          description={`${creator.display_name}. Вывод средств закроется, новые комиссии будут придерживаться, доступ к платным моделям по программе пропадёт. Открытая заявка на вывод будет отклонена.`}
          reason="required"
          confirmLabel="Заблокировать"
          confirmText="Заблокировать креатора? Открытая заявка на вывод будет отклонена."
          danger
          onClose={close}
          onSubmit={async (reason) => {
            const res = await adminBlock(creator.id, reason);
            if (!res.ok) return res.error;
            onChanged("Креатор заблокирован.");
            return null;
          }}
        />
      )}

      {dialog === "unblock" && (
        <ReasonDialog
          title="Разблокировать креатора"
          description={`${creator.display_name}. Придержанные за время блокировки комиссии сами не выпускаются — решение по ним принимается во вкладке «Комиссии».`}
          reason="optional"
          confirmLabel="Разблокировать"
          onClose={close}
          onSubmit={async (reason) => {
            const res = await adminUnblock(creator.id, reason);
            if (!res.ok) return res.error;
            onChanged("Креатор разблокирован.");
            return null;
          }}
        />
      )}

      {dialog === "code" && (
        <ReasonDialog
          title="Изменить промокод"
          description={`${creator.display_name}. Сейчас: ${creator.code || "промокод не создан"}.`}
          reason="required"
          confirmLabel="Изменить промокод"
          canSubmit={codeOk}
          onClose={close}
          onSubmit={async (reason) => {
            const res = await adminChangeCode(creator.id, { code: newCode, reason });
            if (!res.ok) return res.error;
            onChanged(`Промокод изменён: ${res.data.code}.`);
            return null;
          }}
        >
          <label className="block text-sm">
            <span className="text-muted">Новый промокод *</span>
            <input
              value={code}
              onChange={(e) => setCode(e.target.value.toUpperCase())}
              maxLength={16}
              spellCheck={false}
              autoComplete="off"
              placeholder="TORA20"
              className={`${INPUT} mt-1.5 w-full font-mono`}
            />
            {code && !isCodeShape(newCode) && (
              <span className="mt-1 block text-xs text-rose-300">
                От 4 до 16 символов: латинские буквы и цифры, первой идёт буква
              </span>
            )}
            <span className="mt-1 block text-xs text-muted-2">
              Старый код останется рабочим псевдонимом: ссылки и публикации с ним продолжат работать.
            </span>
          </label>
        </ReasonDialog>
      )}

      {dialog === "credits" && (
        <ReasonDialog
          title="Начислить Creator Credits"
          description={`${creator.display_name}. Кредиты выдаются только вручную; их нельзя вывести, перевести или обменять на USDT.`}
          reason="hidden"
          confirmLabel="Начислить"
          canSubmit={amountOk && Boolean(categoryLabel)}
          confirmText={`Начислить ${amountOk ? nf(amountValue) : ""} Creator Credits креатору ${creator.display_name}?\nПричина: ${categoryLabel || ""}`}
          onClose={close}
          onSubmit={async () => {
            const res = await adminGrantCredits(creator.id, { amount: amountValue, category, note: note.trim() });
            if (!res.ok) return res.error;
            onChanged(
              `Начислено ${nf(amountValue)} Creator Credits. Выдано всего: ${nf(res.data.granted)}, осталось: ${nf(res.data.remaining)}.`,
            );
            return null;
          }}
        >
          <div className="block text-sm">
            <label htmlFor="cc-amount" className="text-muted">
              Количество *
            </label>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {CREDIT_PRESETS.map((preset) => (
                <button
                  key={preset}
                  type="button"
                  onClick={() => setAmount(String(preset))}
                  className={amountText === String(preset) ? BTN_ON : BTN}
                >
                  {nf(preset)}
                </button>
              ))}
            </div>
            <input
              id="cc-amount"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              inputMode="numeric"
              placeholder="Своё количество"
              className={`${INPUT} mt-2 w-full`}
            />
            {amountText && !amountOk && (
              <span className="mt-1 block text-xs text-rose-300">Целое число от 1 до {nf(CREDIT_MAX)}</span>
            )}
          </div>
          <label className="block text-sm">
            <span className="text-muted">Причина *</span>
            <select value={category} onChange={(e) => setCategory(e.target.value)} className={`${INPUT} mt-1.5 w-full`}>
              <option value="" disabled>
                Выберите причину
              </option>
              {GRANT_CATEGORIES.map((item) => (
                <option key={item.key} value={item.key}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm">
            <span className="text-muted">Примечание (необязательно) — его увидит креатор</span>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={2}
              maxLength={NOTE_MAX}
              className={`${INPUT} mt-1.5 w-full resize-y`}
            />
          </label>
        </ReasonDialog>
      )}
    </div>
  );
}
