"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { checkCode, createCode } from "@/lib/creators/api";
import { errorText } from "@/lib/creators/errors";
import { isCodeShape } from "@/lib/creators/format";
import type { CodeCreated, CrError } from "@/lib/creators/types";
import { BTN_GHOST, BTN_PRIMARY, INPUT, Note } from "./ui";

type Props = {
  onCreated: (created: CodeCreated) => void;
  /** Код уже создан в другой вкладке (code_already_set) — перечитать кабинет. */
  onReload: () => void;
};

/** Итог проверки кода, для которого она делалась: ответ для старого ввода не показываем. */
type Check = { code: string; available: boolean; reason?: string; error?: CrError };

const DEBOUNCE_MS = 400;

/**
 * Создание промокода (ТЗ п.9): одно поле и «Сохранить». Код создаётся один
 * раз, дальше его меняет только администратор, поэтому перед сохранением —
 * строка подтверждения. Ссылку отдельно создавать не нужно: она и есть код.
 */
export default function CreateCode({ onCreated, onReload }: Props) {
  const { t } = useTranslation("creators", { useSuspense: false });
  const [value, setValue] = useState("");
  const [check, setCheck] = useState<Check | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<CrError | null>(null);

  const shaped = isCodeShape(value);

  // Свободен ли код — спрашиваем, когда человек перестал печатать.
  useEffect(() => {
    if (!shaped) return;
    let alive = true;
    const timer = setTimeout(async () => {
      const res = await checkCode(value);
      if (!alive) return;
      setCheck(
        res.ok
          ? { code: value, available: res.data.available, reason: res.data.reason }
          : { code: value, available: false, error: res.error },
      );
    }, DEBOUNCE_MS);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [value, shaped]);

  const current = shaped && check && check.code === value ? check : null;
  const available = Boolean(current?.available);

  const onChange = (raw: string) => {
    // Код хранится заглавными; пробелы при вставке из мессенджера не нужны.
    setValue(raw.replace(/\s+/g, "").toUpperCase().slice(0, 16));
    setConfirm(false);
    setSaveError(null);
  };

  const save = async () => {
    setSaving(true);
    setSaveError(null);
    const code = value;
    const res = await createCode(code);
    setSaving(false);
    setConfirm(false);
    if (res.ok) {
      onCreated(res.data);
      return;
    }
    const reason = res.error.code;
    if (reason === "code_taken" || reason === "code_reserved" || reason === "code_format") {
      // Код заняли, пока человек подтверждал: причина встаёт под полем, а
      // кнопка «Сохранить» для этого кода гаснет.
      setCheck({ code, available: false, reason });
      return;
    }
    setSaveError(res.error);
    if (reason === "code_already_set") onReload();
  };

  let hint: { tone: "ok" | "fail" | "muted"; text: string } | null = null;
  if (!value) hint = null;
  else if (!shaped) hint = { tone: "fail", text: errorText(t, { code: "code_format" }) };
  else if (!current) hint = { tone: "muted", text: t("dash.code.checking", { defaultValue: "Проверяю…" }) };
  else if (current.error) hint = { tone: "fail", text: errorText(t, current.error) };
  else if (current.available) hint = { tone: "ok", text: t("dash.code.free", { defaultValue: "Промокод свободен" }) };
  else hint = { tone: "fail", text: errorText(t, { code: current.reason || "code_taken" }) };

  const title = t("dash.code.create_title", { defaultValue: "Создайте свой промокод" });

  return (
    <section className="rounded-2xl border border-accent/50 bg-surface p-3">
      <h2 className="text-base font-semibold text-foreground">{title}</h2>
      <form
        className="mt-2 flex items-stretch gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (available && !saving) setConfirm(true);
        }}
      >
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="TORA20"
          maxLength={16}
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          aria-label={title}
          aria-invalid={hint?.tone === "fail"}
          disabled={saving}
          className={`${INPUT} flex-1 font-mono uppercase tracking-wide`}
        />
        <button type="submit" disabled={!available || saving || confirm} className={BTN_PRIMARY}>
          {t("dash.code.save", { defaultValue: "Сохранить" })}
        </button>
      </form>

      {hint && (
        <Note tone={hint.tone} className="mt-1.5">
          {hint.text}
        </Note>
      )}

      {confirm && (
        <div className="mt-2 rounded-xl border border-border bg-surface-2 p-3">
          <p className="break-words text-sm text-foreground">
            {t("dash.code.confirm", {
              defaultValue: "Сохранить промокод {{code}}? Изменить его сможет только администратор.",
              code: value,
            })}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <button type="button" onClick={() => void save()} disabled={saving} className={BTN_PRIMARY}>
              {saving
                ? t("dash.common.saving", { defaultValue: "Сохраняю…" })
                : t("dash.code.confirm_yes", { defaultValue: "Да, сохранить" })}
            </button>
            <button type="button" onClick={() => setConfirm(false)} disabled={saving} className={BTN_GHOST}>
              {t("dash.common.cancel", { defaultValue: "Отмена" })}
            </button>
          </div>
        </div>
      )}

      {saveError && (
        <Note tone="fail" className="mt-1.5">
          {errorText(t, saveError)}
        </Note>
      )}

      <p className="mt-2 text-xs text-muted">
        {t("dash.code.create_hint", {
          defaultValue:
            "От 4 до 16 символов: латинские буквы и цифры, первой идёт буква. Изменить промокод потом сможет только администратор.",
        })}
      </p>
    </section>
  );
}
