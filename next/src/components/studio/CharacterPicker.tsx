"use client";

import { useRef, useState } from "react";
import { FiLoader, FiPlus, FiUpload, FiZap } from "react-icons/fi";
import { fetchData } from "@/tools/fetchData";

export type StudioCharacter = {
  id: number;
  name: string;
  image: string;
  source: string;
  is_mine: boolean;
  category?: string;
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
  characters,
  value,
  onPick,
  onCreated,
  balance,
}: {
  characters: StudioCharacter[];
  value: StudioCharacter | null;
  onPick: (c: StudioCharacter) => void;
  onCreated: (c: StudioCharacter) => void;
  balance: number | null;
}) {
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState<"upload" | "generate" | null>(null);
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement | null>(null);

  const upload = async (file: File) => {
    setBusy("upload");
    setError("");
    const fd = new FormData();
    fd.append("image", file);
    fd.append("name", file.name.replace(/\.[^.]+$/, "").slice(0, 60) || "Мой персонаж");
    const res = await fetchData<StudioCharacter>("cartoon/characters/", "POST", fd, true);
    setBusy(null);
    if (res.ok && res.data) {
      onCreated(res.data);
      onPick(res.data);
    } else {
      setError((res.data as any)?.detail || "Не удалось загрузить изображение");
    }
  };

  const generate = async () => {
    const p = prompt.trim();
    if (!p) {
      setError("Опишите героя: кто он и как выглядит");
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
      setError(
        d?.required
          ? `Не хватает кредитов: нужно ${d.required}, на балансе ${d.balance}`
          : d?.detail || "Не удалось нарисовать персонажа"
      );
    }
  };

  return (
    <section className="flex flex-col gap-4">
      <div>
        <h2 className="text-lg font-bold text-foreground">1. Кто будет героем</h2>
        <p className="text-sm text-muted mt-0.5">
          Выберите из библиотеки, загрузите своего или нарисуйте по описанию. Этот герой
          останется одинаковым во всех сценах.
        </p>
      </div>

      <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-6 gap-2.5">
        {characters.map((c) => {
          const active = value?.id === c.id;
          return (
            <button
              key={c.id}
              type="button"
              onClick={() => onPick(c)}
              className={`group relative aspect-square overflow-hidden rounded-xl border-2 transition-all cursor-pointer ${
                active ? "border-accent shadow-lg" : "border-border hover:border-accent/50"
              }`}
              title={c.name}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={c.image} alt={c.name} className="h-full w-full object-cover" />
              <span className="absolute inset-x-0 bottom-0 truncate bg-black/60 px-1.5 py-1 text-[11px] text-white">
                {c.name}
              </span>
            </button>
          );
        })}

        {/* Загрузка своего — тот же размер плитки, чтобы ряд не рвался. */}
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          disabled={busy !== null}
          className="flex aspect-square flex-col items-center justify-center gap-1.5 rounded-xl border-2 border-dashed border-border text-muted transition-colors hover:border-accent/60 hover:text-foreground disabled:opacity-60 cursor-pointer"
        >
          {busy === "upload" ? (
            <FiLoader className="animate-spin text-xl" />
          ) : (
            <FiUpload className="text-xl" />
          )}
          <span className="text-[11px]">Загрузить</span>
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

      <div className="rounded-2xl border border-border bg-surface-2/60 p-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <FiZap className="text-accent" />
          Нарисовать героя
        </div>
        <p className="mt-1 text-xs text-muted-2">
          Опишите словами: «рыжий кот-супергерой в синем плаще», «девочка-космонавт с
          рыжими косичками».
        </p>
        <div className="mt-2 flex flex-col gap-2 sm:flex-row">
          <input
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !busy) void generate();
            }}
            placeholder="Кто ваш герой?"
            className="flex-1 rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm text-foreground outline-none placeholder:text-muted-2 focus:border-accent"
          />
          <button
            type="button"
            onClick={() => void generate()}
            disabled={busy !== null}
            className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-on-accent transition-colors hover:bg-accent-strong disabled:opacity-60 cursor-pointer"
          >
            {busy === "generate" ? <FiLoader className="animate-spin" /> : <FiPlus />}
            {busy === "generate" ? "Рисую…" : "Нарисовать"}
          </button>
        </div>
        {balance !== null && (
          <p className="mt-1.5 text-[11px] text-muted-2">На балансе {balance} кредитов</p>
        )}
      </div>

      {error && <p className="text-sm text-red-400">{error}</p>}
    </section>
  );
}
