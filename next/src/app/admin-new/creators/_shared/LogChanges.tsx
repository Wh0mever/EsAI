/** «Было → стало» записи журнала: слепки before / after короткими парами «ключ: значение». */

function show(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "да" : "нет";
  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }
  return String(value);
}

function Pairs({ data }: { data: Record<string, unknown> | null | undefined }) {
  const entries = Object.entries(data || {});
  if (entries.length === 0) return <span className="text-muted-2">—</span>;
  return (
    <ul className="space-y-0.5">
      {entries.map(([name, value]) => (
        <li key={name} className="break-all">
          <span className="text-muted-2">{name}:</span> {show(value)}
        </li>
      ))}
    </ul>
  );
}

export default function LogChanges({
  before,
  after,
}: {
  before: Record<string, unknown> | null | undefined;
  after: Record<string, unknown> | null | undefined;
}) {
  return (
    <div className="space-y-1 font-mono text-[11px] leading-snug">
      <Pairs data={before} />
      <div className="text-muted-2">↓</div>
      <Pairs data={after} />
    </div>
  );
}
