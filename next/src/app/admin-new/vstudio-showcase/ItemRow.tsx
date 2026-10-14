"use client";

import { FiChevronDown, FiChevronUp, FiTrash2 } from "react-icons/fi";
import { REEL_MIN } from "@/components/vstudio/home/showreelData";
import { Badge, CARD, INPUT, Preview, StartFrame, Switch, btn, fmtDate, mediaFacts, type Tone } from "./parts";
import {
  TITLE_MAX,
  isPlacement,
  plural,
  trendsAllowed,
  type Category,
  type ItemChanges,
  type Place,
  type Placement,
  type PlacementOption,
  type ShowcaseItem,
} from "./showcaseAdmin";

/**
 * Метка «где работа на сайте». frame — номер ролика в очереди карусели или в
 * «Трендах», size — сколько мест у её места: в карусели номер не совпадает с
 * местом в списке, потому что она сначала берёт по ролику на сценарий.
 */
function placeBadge(
  place: Place,
  frame: number,
  size: number,
  placement: Placement,
): { tone: Tone; label: string; title: string } {
  const trends = placement === "trends";
  switch (place) {
    case "trend":
      return {
        tone: "accent",
        label: `В трендах · ${frame}`,
        title: "Идёт в «Трендах» первого экрана видеостудии. Номер — место в их сетке, по порядку списка",
      };
    case "reel":
      return {
        tone: "accent",
        label: `В карусели · кадр ${frame}`,
        title:
          "Идёт в карусели первого экрана видеостудии. Номер кадра — место в ней: сначала верхний ролик каждого сценария, затем остальные по порядку списка",
      };
    case "wait":
      return {
        tone: "wait",
        label: "Ждёт карусели",
        title: `Карусель покажет ролики студии, когда их станет не меньше ${REEL_MIN}, — пока в ней сцены мультстудии`,
      };
    case "out":
      return {
        tone: "wait",
        label: `Вне карусели: мест ${size}`,
        title: `Посетители его сейчас не видят: мест в карусели ${size}, а этот ролик в её очереди ${frame}-й. Поднимите его выше или увеличьте «Роликов в карусели»`,
      };
    case "image":
      return {
        tone: "wait",
        label: trends ? "Не видна: картинка" : "Вне карусели: картинка",
        title: trends
          ? "Посетители её не видят: «Тренды» показывают только ролики. Уберите её или замените роликом"
          : "Посетители её сейчас не видят: карусель первого экрана берёт только ролики",
      };
    case "hidden":
      return {
        tone: "muted",
        label: "Скрыта",
        title: "Посетители её не видят: переключатель «Видна» выключен",
      };
    case "over":
      return {
        tone: "wait",
        label: "Не поместилась",
        title: trends
          ? `В «Тренды» уходят только первые ${plural(size, "видимый ролик", "видимых ролика", "видимых роликов")} — поднимите этот выше или скройте лишние`
          : "Сайту уходят только первые видимые работы — поднимите эту выше или скройте лишние",
      };
    case "nofile":
      return {
        tone: "fail",
        label: "Файл удалён",
        title: "Автор удалил результат дубля — посетителям работа не показывается",
      };
  }
}

const ORDER_BTN =
  "flex h-9 w-9 cursor-pointer items-center justify-center rounded-lg border border-border text-muted transition-colors enabled:hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40 sm:h-7 sm:w-9";

type Props = {
  item: ShowcaseItem;
  /** Место в списке своего места (карусели или «Трендов») и длина этого списка. */
  index: number;
  total: number;
  place: Place;
  /**
   * Номер ролика в очереди карусели или в «Трендах», с единицы; 0 — туда он не
   * идёт (картинка, скрыт, без файла).
   */
  frame: number;
  /** Сколько мест у места работы: роликов в карусели или потолок «Трендов». */
  size: number;
  categories: Category[];
  placements: PlacementOption[];
  /** Запрос по этой работе в пути — её поля ждут ответа. */
  busy: boolean;
  /** Порядок сейчас менять нельзя: предыдущая перестановка ещё сохраняется. */
  orderLocked: boolean;
  onPatch: (item: ShowcaseItem, changes: ItemChanges) => void;
  /** Перенести работу в другое место: в карусель или в «Тренды». */
  onPlace: (item: ShowcaseItem, placement: Placement) => void;
  onMove: (item: ShowcaseItem, index: number) => void;
  onRemove: (item: ShowcaseItem) => void;
};

export default function ItemRow({
  item,
  index,
  total,
  place,
  frame,
  size,
  categories,
  placements,
  busy,
  orderLocked,
  onPatch,
  onPlace,
  onMove,
  onRemove,
}: Props) {
  const badge = placeBadge(place, frame, size, item.placement);
  const trends = item.placement === "trends";
  const where = trends ? "в трендах" : "в карусели";
  // Картинку в «Тренды» сервер не примет: вариант виден, но выбрать его нельзя.
  const noTrends = !trends && !trendsAllowed(item);

  const commitTitle = (field: HTMLInputElement) => {
    const value = field.value.trim();
    // Работа без названия на сайте выглядит оборванной — пустое не сохраняем.
    if (value && value !== item.title) onPatch(item, { title: value });
    else field.value = item.title;
  };

  const commitPlace = (field: HTMLInputElement) => {
    // Пустое поле и не число — не «первое место», а «передумал».
    const typed = /^\d+$/.test(field.value.trim()) ? Number(field.value.trim()) : index + 1;
    const target = Math.min(Math.max(typed, 1), total);
    if (target !== index + 1) onMove(item, target - 1);
    else field.value = String(index + 1);
  };

  return (
    <li className={`${CARD} flex flex-col gap-3 p-3 sm:flex-row sm:items-start`}>
      <div className="flex shrink-0 items-center gap-1 sm:flex-col">
        <button
          type="button"
          onClick={() => onMove(item, index - 1)}
          disabled={orderLocked || index === 0}
          aria-label="Поднять выше"
          title="Выше"
          className={ORDER_BTN}
        >
          <FiChevronUp className="h-4 w-4" aria-hidden />
        </button>
        {/* key: после перестановки поле показывает новое место, а не то, что в нём набрали. */}
        <input
          key={index}
          defaultValue={index + 1}
          inputMode="numeric"
          disabled={orderLocked}
          aria-label={`Место ${where}: ${index + 1} из ${total}`}
          title={`Место ${where} — впишите номер, чтобы переставить сразу`}
          onFocus={(e) => e.currentTarget.select()}
          onBlur={(e) => commitPlace(e.currentTarget)}
          onKeyDown={(e) => {
            if (e.key === "Enter") e.currentTarget.blur();
            if (e.key === "Escape") {
              e.currentTarget.value = String(index + 1);
              e.currentTarget.blur();
            }
          }}
          className="h-9 w-11 rounded-lg border border-border bg-surface-2 text-center text-sm tabular-nums text-foreground outline-none focus:border-accent disabled:opacity-60 sm:h-8 sm:w-9"
        />
        <button
          type="button"
          onClick={() => onMove(item, index + 1)}
          disabled={orderLocked || index === total - 1}
          aria-label="Опустить ниже"
          title="Ниже"
          className={ORDER_BTN}
        >
          <FiChevronDown className="h-4 w-4" aria-hidden />
        </button>
        <span className="ml-2 sm:hidden">
          <Badge tone={badge.tone} title={badge.title}>
            {badge.label}
          </Badge>
        </span>
      </div>

      <Preview
        media={item}
        className={`shrink-0 rounded-xl sm:w-56 ${place === "hidden" || place === "nofile" ? "opacity-50" : ""}`}
      />

      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {/* key: ответ сервера (или откат после отказа) заменяет то, что набрано в поле. */}
          <input
            key={item.title}
            defaultValue={item.title}
            maxLength={TITLE_MAX}
            disabled={busy}
            aria-label="Название работы"
            placeholder="Название"
            onBlur={(e) => commitTitle(e.currentTarget)}
            onKeyDown={(e) => {
              if (e.key === "Enter") e.currentTarget.blur();
              if (e.key === "Escape") {
                e.currentTarget.value = item.title;
                e.currentTarget.blur();
              }
            }}
            className={`${INPUT} min-w-0 flex-1 basis-48 font-semibold`}
          />
          <select
            value={item.placement}
            disabled={busy}
            aria-label="Куда"
            title="Куда: карусель первого экрана или «Тренды» под инструментами. Перенесённая работа встаёт первой"
            onChange={(e) => {
              const next = e.target.value;
              if (isPlacement(next) && next !== item.placement) onPlace(item, next);
            }}
            className={`${INPUT} cursor-pointer`}
          >
            {placements.map((option) => {
              const off = option.key === "trends" && noTrends;
              return (
                <option key={option.key} value={option.key} disabled={off}>
                  {off ? `${option.label} — только ролики` : option.label}
                </option>
              );
            })}
          </select>
          {/* Сценарий нужен только карусели: «Тренды» идут подряд, без него. */}
          {!trends && (
            <select
              value={item.category}
              disabled={busy}
              aria-label="Сценарий"
              title="Сценарий — под этим названием ролик стоит в карусели"
              onChange={(e) => onPatch(item, { category: e.target.value })}
              className={`${INPUT} cursor-pointer`}
            >
              {!categories.some((category) => category.key === item.category) && (
                <option value={item.category}>{item.category}</option>
              )}
              {categories.map((category) => (
                <option key={category.key} value={category.key}>
                  {category.label}
                </option>
              ))}
            </select>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-2">
          <span className="hidden sm:inline-flex">
            <Badge tone={badge.tone} title={badge.title}>
              {badge.label}
            </Badge>
          </span>
          <span className="min-w-0 truncate">
            {item.modelName ? `${item.modelName} · ` : ""}
            {mediaFacts(item)}
          </span>
          <span className="min-w-0 truncate" title={item.addedBy ? `В витрину поставил ${item.addedBy}` : undefined}>
            {[item.authorEmail, item.createdAt ? `в витрине с ${fmtDate(item.createdAt)}` : ""].filter(Boolean).join(" · ")}
          </span>
        </div>

        {item.prompt && (
          <p className="line-clamp-2 break-words text-xs text-muted" title={item.prompt}>
            {item.prompt}
          </p>
        )}

        <div className="mt-auto flex flex-wrap items-center gap-x-5 gap-y-1">
          <Switch
            on={item.visible}
            label="Видна"
            title="Выключите, чтобы убрать работу с сайта, не удаляя из списка"
            disabled={busy}
            onChange={(visible) => onPatch(item, { visible })}
          />
          {/* Первый кадр — рядом с переключателем, который делает его видимым: проверить до включения. */}
          <span className="inline-flex items-center gap-2">
            <Switch
              on={item.showPrompt}
              label="Показывать запрос"
              title={
                item.prompt
                  ? "По запросу работает кнопка «Снять похожее»: текст и параметры подставятся в студию посетителя. У работ с первым кадром станет виден и он"
                  : "У этого дубля нет текста запроса"
              }
              disabled={busy || (!item.prompt && !item.showPrompt)}
              onChange={(showPrompt) => onPatch(item, { showPrompt })}
            />
            {item.startFrame && <StartFrame src={item.startFrame} shown={item.showPrompt} />}
          </span>
          <button type="button" onClick={() => onRemove(item)} disabled={busy} className={`${btn("danger")} ml-auto`}>
            <FiTrash2 className="h-3.5 w-3.5" aria-hidden />
            Убрать
          </button>
        </div>
      </div>
    </li>
  );
}
