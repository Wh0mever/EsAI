"use client";

import clsx from "clsx";
import Link from "next/link";
import { useState } from "react";
import { FiLogIn } from "react-icons/fi";
import { useAuthedHint } from "@/components/bootstrap/AuthHint";
import { useCt } from "@/lib/creative/text";
import { CREATIVE_TOOLS } from "@/lib/creative/tools";
import { CREATIVE_PATH } from "@/lib/nav/paths";
import { rememberReturnPath } from "@/tools/authNext";
import { ToolBack } from "@/components/creative/ToolSoon";
import { SelectBox } from "@/components/creative/run/Controls";
import { useCreativeAccess } from "@/components/creative/run/useCreativeAccess";
import { BTN_GOLD, CARD, Skeleton } from "@/components/creative/run/ui";
import WorksList from "./WorksList";

/**
 * /creative/works — все работы человека во всех инструментах, с фильтром.
 * Сервер и первый кадр рисуют заголовок и скелет; вход и доступ — после монтирования.
 */
const SELF = `${CREATIVE_PATH}/works`;

export default function WorksPage() {
  const { ct, lang } = useCt();
  const authed = useAuthedHint();
  const access = useCreativeAccess();
  const [tool, setTool] = useState("");

  const options = [
    { value: "", label: ct("works.all_tools") },
    ...[...CREATIVE_TOOLS]
      .sort((a, b) => a.n - b.n)
      .map((t) => {
        const key = `tools.${t.id}.name`;
        const name = ct(key);
        return { value: t.id, label: name === key ? t.name : name };
      }),
  ];

  let body: React.ReactNode;
  if (access.status === "loading") {
    body = (
      <div className="grid grid-cols-[minmax(0,1fr)] gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-busy="true" aria-label={ct("works.loading")}>
        {Array.from({ length: 3 }, (_, i) => (
          <Skeleton key={i} className="h-28" />
        ))}
      </div>
    );
  } else if (!authed || (access.status === "ready" && !access.data.available && access.data.mode === "on")) {
    body = (
      <div className={clsx(CARD, "flex flex-col items-start gap-3 p-5 sm:flex-row sm:items-center sm:justify-between")}>
        <p className="text-sm text-muted">{ct("works.signin")}</p>
        <Link href={`/auth/signin?next=${encodeURIComponent(SELF)}`} onClick={() => rememberReturnPath(SELF)} className={BTN_GOLD}>
          <FiLogIn aria-hidden="true" className="size-4" />
          {ct("works.signin_btn")}
        </Link>
      </div>
    );
  } else if (access.status === "ready" && !access.data.available) {
    body = <p className={clsx(CARD, "p-5 text-sm text-muted")}>{ct("works.closed")}</p>;
  } else {
    // Снимок доступа не пришёл (сеть) — всё равно пробуем список: он сам покажет ошибку.
    body = (
      <>
        <div className="mb-5 max-w-xs space-y-1.5">
          <label htmlFor="cs-works-filter" className="block text-sm font-semibold">
            {ct("works.filter_label")}
          </label>
          <SelectBox id="cs-works-filter" value={tool} options={options} onChange={setTool} />
        </div>
        <WorksList tool={tool || undefined} ct={ct} lang={lang} showTool labelledBy="cs-works-h1" />
      </>
    );
  }

  return (
    <main className="mx-auto max-w-7xl px-4 pb-16 pt-28 sm:px-6 sm:pt-32 lg:px-8">
      <ToolBack />
      <header className="mb-6 mt-3">
        <h1 id="cs-works-h1" className="text-3xl font-extrabold leading-tight sm:text-4xl">
          {ct("works.title")}
        </h1>
        <p className="mt-2 max-w-2xl text-muted">{ct("works.subtitle")}</p>
      </header>
      {body}
    </main>
  );
}
