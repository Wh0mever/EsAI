import { NextResponse } from "next/server";

export async function GET() {
  // Отдаём браузеру ТОЛЬКО публичные значения (NEXT_PUBLIC_*).
  // Серверные/непубличные env (FREEDOM_PAY_*) НИКОГДА не уходят на фронт.
  const pk = process.env.NEXT_PUBLIC_FREEDOM_PAY_PUBLIC_KEY || "";
  // ТОЛЬКО публичный SDK-токен. НИКОГДА не отдаём серверный секрет подписи FREEDOM_PAY_TOKEN на фронт.
  const token = process.env.NEXT_PUBLIC_FREEDOM_PAY_TOKEN || "";
  const test = (
    process.env.NEXT_PUBLIC_FREEDOM_PAY_TEST
    || process.env.NEXT_PUBLIC_FREEDOM_PAY_TEST_MODE
    || process.env.NEXT_PUBLIC_FREEDOMPAY_TEST
    || ""
  ).toString();
  const merchantId = process.env.NEXT_PUBLIC_FREEDOM_PAY_MERCHANT_ID || "";
  return NextResponse.json({
    NEXT_PUBLIC_FREEDOM_PAY_PUBLIC_KEY: pk,
    NEXT_PUBLIC_FREEDOM_PAY_TOKEN: token,
    NEXT_PUBLIC_FREEDOM_PAY_TEST: test,
    NEXT_PUBLIC_FREEDOM_PAY_MERCHANT_ID: merchantId,
  });
}
