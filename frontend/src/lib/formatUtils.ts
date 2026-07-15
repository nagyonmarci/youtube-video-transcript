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

export function formatDurationWords(seconds: number | null | undefined): string {
  const total = Number(seconds || 0);
  if (!total) return '';
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours) return `${hours}h ${minutes}m ${secs}s`;
  if (minutes) return `${minutes}m ${secs}s`;
  return `${secs}s`;
}

export function formatJobTime(value: string | null | undefined): string {
  if (!value) return '';
  return new Date(value).toLocaleString('hu-HU', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '';
  return new Date(iso).toLocaleString('hu-HU', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}
