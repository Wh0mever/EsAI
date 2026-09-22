"use client";

import { useTranslation } from "react-i18next";
import { useRef, useState } from "react";
import { FiLoader, FiPlus, FiUpload, FiX, FiZap } from "react-icons/fi";
import { fetchData } from "@/tools/fetchData";

export type StudioCharacter = {
  id: number;
  name: string;
  image: string;
  source: string;
  is_mine: boolean;
  category?: string;
  /** Для кого герой — берётся из его раздела; свои персонажи всегда видны. */
  audience?: "kids" | "adults";
};

/**
 * CharacterPicker — первый шаг студии: кто будет героем мультфильма.
 *
 * Три пути, как просил клиент: взять готового, загрузить своего, нарисовать по
 * описанию. Это единственное место, где человек вообще что-то придумывает —
 * дальше он только выбирает готовые сцены.
 *
 * Персонаж важнее, чем кажется: именно его изображение потом переносится в
 * каждую сцену как референс и удерживает героя одинаковым. Поэтому лучше
 * работают карточки в полный рост на простом фоне — их и рисует генератор.
 */
export default function CharacterPicker({
  authed = true,
  onNeedAuth,
  onNeedCredits,
  characters,
  value,
  onPick,
  onCreated,
  onDeleted,
  balance,
}: {
  /** Вошёл ли человек: гостю нельзя ни загрузить своего героя, ни нарисовать. */
  authed?: boolean;
  /** Позвать окно входа вместо строчки с ошибкой под формой. */
  onNeedAuth?: () => void;
  /** Не хватило кредитов на своего героя — показать окно оплаты.
   *  Раньше это была красная строка под формой, которой клиент не увидел. */
  onNeedCredits?: (required: number, balance: number) => void;
  characters: StudioCharacter[];
  value: StudioCharacter | null;
  onPick: (c: StudioCharacter) => void;
  onCreated: (c: StudioCharacter) => void;
  /** Свой герой удалён — убрать из списка. */
  onDeleted?: (id: number) => void;
  balance: number | null;
}) {
  const { t } = useTranslation("common");
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState<"upload" | "generate" | null>(null);
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [expanded, setExpanded] = useState(false);

  // Девять героев в свёрнутом виде. Выбранный — всегда среди них: иначе
  // человек выбрал бы героя из раскрытого списка, свернул — и потерял его из виду.
  const COLLAPSED = 9;
  // Свои персонажи — в самом начале (клиент): человек загрузил их сам и ищет
  // первыми, а не среди двух десятков библиотечных.
  const ordered = [...characters.filter((c) => c.is_mine), ...characters.filter((c) => !c.is_mine)];
  const shownCharacters = (() => {
    if (expanded || ordered.length <= COLLAPSED) return ordered;
    const head = ordered.slice(0, COLLAPSED);
    if (value && !head.some((c) => c.id === value.id)) {
      const picked = ordered.find((c) => c.id === value.id);
      if (picked) return [...head.slice(0, COLLAPSED - 1), picked];
    }
    return head;
  })();
  const hiddenCount = Math.max(0, characters.length - COLLAPSED);

  /** Удалить своего героя. Клиент: «надо, чтоб своего героя можно было удалить». */
  const remove = async (c: StudioCharacter) => {
    if (!confirm(t("studio_ui.hero_delete_confirm", { name: c.name }))) return;
    setError("");
    const res = await fetchData(`cartoon/characters/${c.id}/`, "DELETE", null, true);
    if (res.ok) onDeleted?.(c.id);
    else setError((res.data as any)?.detail || t("studio_ui.err_upload"));
  };

  const upload = async (file: File) => {
    setBusy("upload");
    setError("");
    const fd = new FormData();
    fd.append("image", file);
    fd.append("name", file.name.replace(/\.[^.]+$/, "").slice(0, 60) || t("studio_ui.my_character"));
    const res = await fetchData<StudioCharacter>("cartoon/characters/", "POST", fd, true);
    setBusy(null);
    if (res.ok && res.data) {
      onCreated(res.data);
      onPick(res.data);
    } else {
      setError((res.data as any)?.detail || t("studio_ui.err_upload"));
    }
  };

  const generate = async () => {
    if (!authed) {
      onNeedAuth?.();
      return;
    }
    const p = prompt.trim();
    if (!p) {
      setError(t("studio_ui.err_describe"));
      return;
    }
    setBusy("generate");
    setError("");
    const res = await fetchData<StudioCharacter>(
      "cartoon/characters/generate/", "POST", { prompt: p }, true
    );
    setBusy(null);
    if (res.ok && res.data) {
      onCreated(res.data);
      onPick(res.data);
      setPrompt("");
    } else {
      const d = res.data as any;
      if (d?.required) {
        onNeedCredits?.(Number(d.required), Number(d.balance ?? 0));
      } else {
        setError(d?.detail || t("studio_ui.err_draw"));
      }
    }
  };

  return (
    <section className="flex flex-col gap-4">
      <div>
        <h2 className="text-lg font-bold text-foreground">{t("studio_ui.step1")}</h2>
        <p className="text-sm text-muted mt-0.5">
          {t("studio_ui.step1_note")}
        </p>
      </div>

      {/* Героев больше двух десятков, и сеткой во всю ширину они захламляли
          страницу (клиент). Показываем девять — три на три, — остальные по
          кнопке. Выбранный герой всегда виден, даже если он из скрытых. */}
      <div className="grid max-w-xl grid-cols-3 gap-2.5">
        {shownCharacters.map((c) => {
          const active = value?.id === c.id;
          return (
            <div key={c.id} className="relative">
            <button
              type="button"
              onClick={() => onPick(c)}
              className={`group relative aspect-square w-full overflow-hidden rounded-xl border-2 transition-all cursor-pointer ${
                active ? "border-accent shadow-lg" : "border-border hover:border-accent/50"
              }`}
              title={c.name}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={c.image}
                alt={c.name}
                loading="lazy"
                decoding="async"
                className="h-full w-full object-cover"
              />
              <span className="absolute inset-x-0 bottom-0 truncate bg-black/60 px-1.5 py-1 text-[11px] text-white">
                {c.name}
              </span>
            </button>
            {/* Своего героя можно убрать. Библиотечных — нет: они общие. */}
            {c.is_mine && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  void remove(c);
                }}
                title={t("studio_ui.hero_delete")}
                aria-label={t("studio_ui.hero_delete")}
                className="absolute right-1 top-1 grid size-6 place-items-center rounded-full bg-black/60 text-white transition-colors hover:bg-red-500 cursor-pointer"
              >
                <FiX className="text-sm" />
              </button>
            )}
            </div>
          );
        })}

      </div>

      <div className="flex max-w-xl flex-wrap items-center gap-2">
        {hiddenCount > 0 && (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface px-4 py-2 text-sm font-medium text-muted transition-colors hover:border-accent hover:text-foreground cursor-pointer"
          >
            {expanded ? t("studio_ui.collapse") : t("studio_ui.show_more")}
            {!expanded && <span className="text-muted-2">{hiddenCount}</span>}
          </button>
        )}
        {/* Загрузка своего — кнопкой рядом, а не плиткой: плитка ломала сетку 3×3. */}
        <button
          type="button"
          onClick={() => {
            // Гостю сюда нельзя: раньше он узнавал об этом строчкой под
            // формой, которой не видно (жалоба клиента).
            if (!authed) {
              onNeedAuth?.();
              return;
            }
            fileRef.current?.click();
          }}
          disabled={busy !== null}
          className="inline-flex items-center gap-1.5 rounded-full border border-dashed border-border px-4 py-2 text-sm text-muted transition-colors hover:border-accent/60 hover:text-foreground disabled:opacity-60 cursor-pointer"
        >
          {busy === "upload" ? <FiLoader className="animate-spin" /> : <FiUpload />}
          {t("studio_ui.upload")}
        </button>
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void upload(f);
            e.target.value = "";
          }}
        />
      </div>

      {/* Клиент: человек не понимал, куда вводить описание — поле выглядело
          как строка-пример. Поэтому схема простая и одинаковая во всей студии:
          заголовок → короткая подсказка → большое поле → кнопка во всю ширину. */}
      <div className="max-w-xl rounded-2xl border border-border bg-surface-2/60 p-4">
        <div className="flex items-center gap-2 text-base font-bold text-foreground">
          <FiZap className="text-accent" />
          {t("studio_ui.draw_title")}
        </div>
        <p className="mt-1 text-sm text-muted">
          {t("studio_ui.draw_note")}
        </p>
        <div className="mt-3 flex flex-col gap-2">
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value.slice(0, 300))}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !busy) {
                e.preventDefault();
                void generate();
              }
            }}
            rows={2}
            placeholder={t("studio_ui.draw_placeholder")}
            className="w-full resize-none rounded-xl border-2 border-border bg-surface px-4 py-3 text-base text-foreground shadow-inner outline-none transition-colors placeholder:text-muted focus:border-accent"
          />
          <button
            type="button"
            onClick={() => void generate()}
            disabled={busy !== null}
            className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-accent px-5 py-3 text-base font-bold text-on-accent transition-colors hover:bg-accent-strong disabled:opacity-60 cursor-pointer"
          >
            {busy === "generate" ? <FiLoader className="animate-spin" /> : <FiPlus />}
            {busy === "generate" ? t("studio_ui.drawing") : t("studio_ui.draw_btn")}
          </button>
        </div>
        {balance !== null && (
          <p className="mt-2 text-xs text-muted-2">{t("studio_ui.balance", { count: balance })}</p>
        )}
      </div>

      {error && <p className="text-sm text-red-400">{error}</p>}
    </section>
  );
}
