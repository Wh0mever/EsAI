"use client";

import { FiFilm } from "react-icons/fi";
import { Badge, CARD } from "./parts";
import type { Carousel } from "./showcaseAdmin";

/**
 * «Сценарии карусели»: двенадцать сценариев первого экрана и чем каждый занят.
 * Клиент просил по ролику на сценарий — по доске видно, какие ещё не сняты,
 * не листая витрину. Занят сценарий верхним роликом из тех, что видит сайт;
 * скрытые и картинки не в счёт. Размер карусели задаёт владелец: если он
 * больше числа сценариев, под ними идут остальные ролики в том же порядке,
 * что на сайте; если меньше — сценарии, которым места не хватило, приглушены.
 */
type Props = {
  carousel: Carousel;
  /** Сколько роликов студии нужно карусели, чтобы она показывала их, а не мультстудию. */
  min: number;
};

export default function ScenarioBoard({ carousel, min }: Props) {
  const { slots, filled, videos, studio, order, tail } = carousel;
  // С какого кадра карусели начинаются ролики после сценариев.
  const tailFrom = order.length - tail.length + 1;
  return (
    <section className={`${CARD} flex flex-col gap-3 p-3 sm:p-4`}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <h2 className="text-base font-semibold">Сценарии карусели</h2>
        <span className="text-xs tabular-nums text-muted-2">
          Заполнено {filled} из {slots.length}
        </span>
        <span className="sm:ml-auto">
          {studio ? (
            <Badge tone="accent" title="Посетители видят в карусели ролики студии">
              Идут ролики студии
            </Badge>
          ) : (
            <Badge tone="wait" title="Посетители видят в карусели сцены мультстудии: роликов студии пока не хватает">
              Идут сцены мультстудии: роликов {videos} из {min}
            </Badge>
          )}
        </span>
      </div>

      <ol className="grid grid-cols-3 gap-2 sm:grid-cols-4 lg:grid-cols-6">
        {slots.map((slot, index) => {
          const still = slot.item ? (slot.item.poster ?? slot.item.image) : null;
          const cut = slot.item !== null && !slot.fits;
          return (
            <li key={slot.key} className="min-w-0">
              {slot.item ? (
                <div
                  title={cut ? "Ролик снят, но в карусель не вошёл: мест в ней меньше, чем занятых сценариев" : undefined}
                  className="relative aspect-video overflow-hidden rounded-lg bg-black"
                >
                  {still ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={still}
                      alt=""
                      loading="lazy"
                      decoding="async"
                      className={`h-full w-full object-cover ${cut ? "opacity-40" : ""}`}
                    />
                  ) : (
                    <div className="flex h-full w-full items-center justify-center text-white/40">
                      <FiFilm className="h-5 w-5" aria-hidden />
                    </div>
                  )}
                  {cut && (
                    <span className="absolute inset-x-0 bottom-0 bg-black/70 px-1 py-0.5 text-center text-[10px] font-medium text-white">
                      вне карусели
                    </span>
                  )}
                  {slot.spare > 0 && (
                    <span
                      title={`Роликов этого сценария на сайте ещё ${slot.spare}. Сценарий показывает верхний в списке, остальные идут на свободные места карусели`}
                      className="absolute right-1 top-1 rounded-full bg-black/70 px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-white"
                    >
                      +{slot.spare}
                    </span>
                  )}
                </div>
              ) : (
                <div className="flex aspect-video items-center justify-center rounded-lg border border-dashed border-border text-[11px] text-muted-2">
                  пусто
                </div>
              )}
              <div
                title={slot.label}
                className={`mt-1.5 truncate text-xs font-medium ${slot.item && !cut ? "text-foreground" : "text-muted"}`}
              >
                <span className="tabular-nums text-muted-2">{index + 1}.</span> {slot.label}
              </div>
              {slot.item && (
                <div title={slot.item.title || undefined} className="truncate text-[11px] text-muted-2">
                  {slot.item.title || "Без названия"}
                </div>
              )}
            </li>
          );
        })}
      </ol>

      {/* Пока в карусели сцены мультстудии, порядка роликов студии в ней нет — показывать нечего. */}
      {studio && tail.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <div className="text-xs text-muted-2">После сценариев — остальные ролики карусели, по порядку списка:</div>
          <ol start={tailFrom} className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
            {tail.map((item, index) => (
              <li key={item.id} title={item.title || undefined} className="min-w-0 max-w-full truncate sm:max-w-56">
                <span className="tabular-nums text-muted-2">{tailFrom + index}.</span> {item.title || "Без названия"}
              </li>
            ))}
          </ol>
        </div>
      )}

      <p className="text-xs text-muted-2">
        Карусель на первом экране показывает ролики студии, когда их не меньше {min}; до этого — сцены
        мультстудии.
      </p>
    </section>
  );
}
