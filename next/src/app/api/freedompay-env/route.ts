import { NextResponse } from "next/server";

export async function GET() {
  const pk = process.env.NEXT_PUBLIC_FREEDOM_PAY_PUBLIC_KEY || process.env.FREEDOM_PAY_PUBLIC_KEY || "";
  const token = process.env.NEXT_PUBLIC_FREEDOM_PAY_TOKEN || process.env.FREEDOM_PAY_TOKEN || "";
  const test = (
    process.env.NEXT_PUBLIC_FREEDOM_PAY_TEST
    || process.env.NEXT_PUBLIC_FREEDOM_PAY_TEST_MODE
    || (process as any).env.NEXT_PUBLIC_FREEDOMPAY_TEST
    || process.env.FREEDOM_PAY_TEST
    || ""
  ).toString();
  const merchantId = process.env.NEXT_PUBLIC_FREEDOM_PAY_MERCHANT_ID || process.env.FREEDOM_PAY_MERCHANT_ID || "";
  return NextResponse.json({
    NEXT_PUBLIC_FREEDOM_PAY_PUBLIC_KEY: pk,
    NEXT_PUBLIC_FREEDOM_PAY_TOKEN: token,
    NEXT_PUBLIC_FREEDOM_PAY_TEST: test,
    NEXT_PUBLIC_FREEDOM_PAY_MERCHANT_ID: merchantId,
  });
}
