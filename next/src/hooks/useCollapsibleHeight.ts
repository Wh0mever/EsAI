"use client";

import { useEffect, useRef, useState } from "react";

/**
 * useCollapsibleHeight — общая логика раскрывающегося блока с измеренным
 * max-height (ref.scrollHeight + ResizeObserver), а не CSS-grid-трюком
 * grid-template-rows: 0fr↔1fr. Тот трюк не раскрывал блок визуально
 * (computed height оставался 0 независимо от заданного значения), хотя
 * aria-expanded/JS-состояние переключались верно — воспроизведено и
 * починено при разработке home/HomeCreditsExplainer.tsx. Корень проблемы —
 * элемент был flex-item внутри родителя с display:flex: вложенность
 * overflow-hidden-контейнера с анимируемым размером в такой родитель ломала
 * расчёт intrinsic-высоты. Измеренный max-height оставлен как более надёжный
 * способ анимации раскрытия сам по себе (не зависит от grid/flex-контекста
 * родителя). ResizeObserver подстраивает высоту, если контент дозагрузится/
 * изменится уже после раскрытия (например, таблица моделей из ai/models/
 * приходит асинхронно).
 *
 * Вынесено в хук, чтобы главная страница (HomeCreditsExplainer) и /pricing
 * (CollapsibleCreditsExplainer) переиспользовали ровно тот же проверенный
 * механизм раскрытия, а не две независимые копии одной и той же логики.
 */
export function useCollapsibleHeight(open: boolean) {
  const contentRef = useRef<HTMLDivElement>(null);
  const [maxHeight, setMaxHeight] = useState(0);

  useEffect(() => {
    const el = contentRef.current;
    if (!el) return;
    if (!open) {
      setMaxHeight(0);
      return;
    }
    setMaxHeight(el.scrollHeight);
    const ro = new ResizeObserver(() => setMaxHeight(el.scrollHeight));
    ro.observe(el);
    return () => ro.disconnect();
  }, [open]);

  return { contentRef, maxHeight };
}
