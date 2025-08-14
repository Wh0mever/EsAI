export type CardInput = {
  number: string;     // digits only
  holder: string;
  expMonth: string;   // "MM"
  expYear: string;    // "YY" or "YYYY"
  cvv: string;
};

export function normalizeYear(yy: string) {
  const y = yy.trim();
  if (y.length === 2) return y;
  if (y.length === 4) return y.slice(2);
  return y;
}

export function joinChunks(chunks: string[]) {
  return chunks.join('').replace(/\D+/g, '');
}

export function validateCardInput(c: CardInput) {
  if (!/^\d{13,19}$/.test(c.number)) return 'Invalid card number';
  if (!/^\d{2}$/.test(c.expMonth) || Number(c.expMonth) < 1 || Number(c.expMonth) > 12) return 'Invalid month';
  if (!/^\d{2,4}$/.test(c.expYear)) return 'Invalid year';
  if (!/^\d{3,4}$/.test(c.cvv)) return 'Invalid CVV';
  if (!c.holder.trim()) return 'Holder required';
  return null;
}
