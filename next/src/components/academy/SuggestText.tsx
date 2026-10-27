import { Fragment } from "react";
import { EXTERNAL_REL, suggestParts } from "@/lib/academy/shared";

/**
 * Текст блока «Предложить курс» (вид text): без кнопки, абзацем под приглашением.
 * Только текстовые узлы React — никакого HTML из настройки; ссылки и адреса почты
 * внутри становятся ссылками (suggestParts решает, что можно поставить в href).
 * Без хуков: его рисуют и страница, и SEO-блок с сервера, и превью в панели.
 */
export default function SuggestText({
  text,
  newTab,
  className,
  linkClassName,
}: {
  text: string;
  /** Подсказка читалке у ссылки на сайт: «(откроется в новой вкладке)». */
  newTab: string;
  className?: string;
  linkClassName?: string;
}) {
  return (
    <p className={className}>
      {suggestParts(text).map((part, i) =>
        part.kind === "text" ? (
          <Fragment key={i}>{part.text}</Fragment>
        ) : part.kind === "url" ? (
          <a key={i} href={part.href} target="_blank" rel={EXTERNAL_REL} className={linkClassName}>
            {part.text}
            <span className="sr-only"> {newTab}</span>
          </a>
        ) : (
          <a key={i} href={part.href} className={linkClassName}>
            {part.text}
          </a>
        ),
      )}
    </p>
  );
}
