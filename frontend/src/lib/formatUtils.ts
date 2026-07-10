// Display formatting helpers for video durations and dates (UI context, not file exports)

export function formatDuration(seconds: number | null | undefined, fallback = '—'): string {
  if (!seconds) return fallback;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${m}:${String(s).padStart(2, '0')}`;
}

export function formatDate(iso: string | null | undefined, fallback = '—'): string {
  if (!iso) return fallback;
  return new Date(iso).toLocaleDateString('hu-HU');
}
