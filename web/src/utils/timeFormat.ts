/** Format seconds as m:ss (e.g. 125 → "2:05"). */
export function formatMmSs(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

/** Parse "m:ss", "mm:ss", or plain seconds string. Returns null if invalid. */
export function parseMmSs(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  if (trimmed.includes(":")) {
    const parts = trimmed.split(":");
    if (parts.length !== 2) return null;
    const m = parseInt(parts[0], 10);
    const s = parseInt(parts[1], 10);
    if (Number.isNaN(m) || Number.isNaN(s) || m < 0 || s < 0 || s >= 60) return null;
    return m * 60 + s;
  }
  const n = parseFloat(trimmed);
  return Number.isFinite(n) && n >= 0 ? n : null;
}

/** Display a time range, e.g. "2:05 – 3:40". */
export function formatRange(start: number, end: number): string {
  return `${formatMmSs(start)} – ${formatMmSs(end)}`;
}
