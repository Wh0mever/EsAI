import { fmtUsdt } from "@/lib/creators/format";

type Props = {
  /** Сумма строкой, как её прислал сервер; знаков после точки не меняем. */
  value: string | null | undefined;
  /** Показывать «USDT» после числа (по умолчанию да). */
  unit?: boolean;
  className?: string;
};

/** Сумма в USDT: разряды пробелом, одной строкой, цифры одной ширины. */
export default function Money({ value, unit = true, className = "" }: Props) {
  return (
    <span className={`whitespace-nowrap tabular-nums ${className}`}>
      {fmtUsdt(value)}
      {unit ? " USDT" : ""}
    </span>
  );
}
