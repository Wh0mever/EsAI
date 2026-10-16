"use client";

import { useTranslation } from "react-i18next";
import { useEffect, useId, useRef, useState } from "react";
import type { KeyboardEvent, RefCallback } from "react";
import { FiLoader, FiPenTool, FiPlus, FiUpload, FiX } from "react-icons/fi";
import { fetchData } from "@/tools/fetchData";
import type { EdgeFade } from "@/components/vstudio/home/strip/stripLogic";
import { EDGE_FADE } from "@/components/vstudio/home/strip/useEdgeFade";
import { VS_BTN_GOLD, VS_CARD, VS_ICON_BTN, VS_INPUT, vx } from "@/components/vstudio/ui/skin";
import type { ApiRefusal } from "./cartoonTypes";
import HeroCard, { HERO_ITEM, HeroActionCard } from "./library/HeroCard";
import { CS_STRIP } from "./ui/cartoonSkin";

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

export type CharacterPickerProps = {
  /** Вошёл ли человек: гостю нельзя ни загрузить своего героя, ни нарисовать. */
  authed?: boolean;
  /** Позвать окно входа вместо строчки с ошибкой под формой. */
  onNeedAuth?: () => void;
  /** Не хватило кредитов на своего героя — показать окно оплаты.
   *  Раньше это была красная строка под формой, которой клиент не увидел. */
  onNeedCredits?: (required: number, balance: number) => void;
  /** Герои в порядке ленты (library/heroOrder). */
  characters: StudioCharacter[];
  value: StudioCharacter | null;
  /** Герои, уже стоящие в сценах открытого мультфильма, — с отметкой. */
  castIds?: ReadonlySet<number>;
  onPick: (c: StudioCharacter) => void;
  onCreated: (c: StudioCharacter) => void;
  /** Свой герой удалён — убрать из списка. */
  onDeleted?: (id: number) => void;
  balance: number | null;
  /** Прокручиваемый блок ленты и край, который гасить (useEdgeFade у секции: стрелки — в её шапке). */
  stripRef?: RefCallback<HTMLDivElement>;
  fade?: EdgeFade;
  /** id заголовка секции — подпись списка героев. */
  labelledBy?: string;
};

const NO_CAST: ReadonlySet<number> = new Set();

/** С этой ширины форма «Нарисовать по описанию» помещается под лентой, не занимая экран. */
const WIDE_QUERY = "(min-width: 768px)";

/** Стрелки и Home/End переводят фокус по карточкам ленты: Tab по двум десяткам героев — долго. */
function moveFocus(e: KeyboardEvent<HTMLUListElement>) {
  const cards = [...e.currentTarget.querySelectorAll<HTMLElement>("[data-hero-card]")];
  const at = cards.indexOf(e.target as HTMLElement);
  if (at < 0) return;
  const to =
    e.key === "ArrowRight" ? at + 1
    : e.key === "ArrowLeft" ? at - 1
    : e.key === "Home" ? 0
    : e.key === "End" ? cards.length - 1
    : -1;
  const next = cards[to];
  if (to < 0 || !next) return;
  e.preventDefault();
  next.focus();
}

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
 *
 * Вид — лента карточек, как в видеостудии: в начале «Загрузить своего» и
 * «Нарисовать по описанию», за ними герои. Форма описания раскрывается под
 * лентой по нажатию — постоянно открытая, она занимала пол-экрана телефона.
 */
export default function CharacterPicker({
  authed = true,
  onNeedAuth,
  onNeedCredits,
  characters,
  value,
  castIds = NO_CAST,
  onPick,
  onCreated,
  onDeleted,
  balance,
  stripRef,
  fade = "none",
  labelledBy,
}: CharacterPickerProps) {
  const { t } = useTranslation("common");
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState<"upload" | "generate" | null>(null);
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement | null>(null);
  // Клиент: человек не находил, где писать описание. Поэтому вошедшему без своих
  // героев форма с 768 px открыта сразу (на телефоне она заняла бы пол-экрана).
  // Лента героев монтирует нас уже после загрузки — список героев известен.
  const [drawOpen, setDrawOpen] = useState(
    () => authed && !characters.some((c) => c.is_mine) && typeof window !== "undefined" && window.matchMedia?.(WIDE_QUERY).matches === true,
  );
  // Открыли нажатием — фокус в поле; открытую с порога не трогаем: курсор в поле
  // увёл бы с начала страницы и на телефоне поднял бы клавиатуру.
  const [drawFocus, setDrawFocus] = useState(false);
  const drawRef = useRef<HTMLButtonElement | null>(null);
  const areaRef = useRef<HTMLTextAreaElement | null>(null);
  const formId = useId();
  const titleId = useId();
  const noteId = useId();

  // Форму открыли — сразу в поле: за этим её и открывали.
  useEffect(() => {
    if (drawOpen && drawFocus) areaRef.current?.focus();
  }, [drawOpen, drawFocus]);

  /** Свернуть форму и вернуть фокус на карточку, которая её открыла. */
  const closeDraw = () => {
    setDrawOpen(false);
    drawRef.current?.focus();
  };

  /** Удалить своего героя. Клиент: «надо, чтоб своего героя можно было удалить». */
  const remove = async (c: StudioCharacter) => {
    if (!confirm(t("studio_ui.hero_delete_confirm", { name: c.name }))) return;
    setError("");
    const res = await fetchData(`cartoon/characters/${c.id}/`, "DELETE", null, true);
    if (res.ok) onDeleted?.(c.id);
    else setError((res.data as ApiRefusal)?.detail || t("studio_ui.err_upload"));
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
      setError((res.data as ApiRefusal)?.detail || t("studio_ui.err_upload"));
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
      // Герой готов и уже выбран — форма своё отработала.
      closeDraw();
    } else {
      const d = res.data as ApiRefusal;
      if (d?.required) {
        onNeedCredits?.(Number(d.required), Number(d.balance ?? 0));
      } else {
        setError(d?.detail || t("studio_ui.err_draw"));
      }
    }
  };

  const uploadLabel = t("studio_ui.heroes_upload", { defaultValue: "Загрузить своего" });
  const drawLabel = t("studio_ui.heroes_draw", { defaultValue: "Нарисовать по описанию" });

  return (
    <>
      {/* Поля по вертикали — чтобы лента не срезала кольцо фокуса карточек. */}
      <div
        ref={stripRef}
        data-hero-strip=""
        className={vx(CS_STRIP, EDGE_FADE[fade], "mt-4 snap-x snap-proximity scroll-px-4 sm:scroll-px-6")}
      >
        <ul aria-labelledby={labelledBy} onKeyDown={moveFocus} className="flex w-max gap-2.5 sm:gap-3">
          <li className={HERO_ITEM}>
            <HeroActionCard
              icon={
                busy === "upload" ? <FiLoader className="animate-spin motion-reduce:animate-none" /> : <FiUpload />
              }
              label={uploadLabel}
              busy={busy === "upload"}
              disabled={busy !== null}
              onClick={() => {
                // Гостю сюда нельзя: раньше он узнавал об этом строчкой под
                // формой, которой не видно (жалоба клиента).
                if (!authed) {
                  onNeedAuth?.();
                  return;
                }
                fileRef.current?.click();
              }}
            />
          </li>
          <li className={HERO_ITEM}>
            <HeroActionCard
              ref={drawRef}
              icon={<FiPenTool />}
              label={drawLabel}
              expanded={drawOpen}
              controls={drawOpen ? formId : undefined}
              onClick={() => {
                if (!authed) {
                  onNeedAuth?.();
                  return;
                }
                setDrawFocus(true);
                setDrawOpen((v) => !v);
              }}
            />
          </li>
          {characters.map((c) => (
            <li key={c.id} className={HERO_ITEM}>
              <HeroCard
                character={c}
                selected={value?.id === c.id}
                inMovie={castIds.has(c.id)}
                onPick={onPick}
                // Своего героя можно убрать. Библиотечных — нет: они общие.
                onDelete={c.is_mine ? () => void remove(c) : undefined}
              />
            </li>
          ))}
        </ul>
      </div>
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

      {/* Клиент: человек не понимал, куда вводить описание — поле выглядело
          как строка-пример. Поэтому схема простая и одинаковая во всей студии:
          заголовок → короткая подсказка → большое поле → кнопка. */}
      {drawOpen && (
        <div id={formId} className={vx(VS_CARD, "mt-3 max-w-xl p-4")}>
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h3 id={titleId} className="text-sm font-semibold text-foreground">
                {drawLabel}
              </h3>
              <p id={noteId} className="mt-1 text-[13px] leading-snug text-muted">
                {t("studio_ui.draw_note")}
              </p>
            </div>
            <button
              type="button"
              onClick={closeDraw}
              aria-label={t("studio_ui.collapse")}
              title={t("studio_ui.collapse")}
              className={vx(VS_ICON_BTN, "-mr-1 -mt-1")}
            >
              <FiX aria-hidden />
            </button>
          </div>
          <textarea
            ref={areaRef}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value.slice(0, 300))}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                e.preventDefault();
                closeDraw();
                return;
              }
              if (e.key === "Enter" && !e.shiftKey && !busy) {
                e.preventDefault();
                void generate();
              }
            }}
            rows={2}
            placeholder={t("studio_ui.draw_placeholder")}
            aria-labelledby={titleId}
            aria-describedby={noteId}
            // !min-h: у VS_INPUT с 768 px своя min-h-10, и поле сжималось до двух строк.
            className={vx(VS_INPUT, "mt-3 !min-h-[76px] resize-none py-2.5 leading-snug max-sm:text-base")}
          />
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
            {balance !== null && (
              <p className="text-xs text-muted-2">{t("studio_ui.balance", { count: balance })}</p>
            )}
            <button
              type="button"
              onClick={() => void generate()}
              disabled={busy !== null}
              aria-busy={busy === "generate" || undefined}
              className={vx(VS_BTN_GOLD, "w-full sm:ml-auto sm:w-auto")}
            >
              {busy === "generate" ? (
                <FiLoader aria-hidden className="animate-spin motion-reduce:animate-none" />
              ) : (
                <FiPlus aria-hidden />
              )}
              {busy === "generate" ? t("studio_ui.drawing") : t("studio_ui.draw_btn")}
            </button>
          </div>
        </div>
      )}

      {error && (
        <p role="alert" className="mt-3 text-sm text-status-fail">
          {error}
        </p>
      )}
    </>
  );
}
