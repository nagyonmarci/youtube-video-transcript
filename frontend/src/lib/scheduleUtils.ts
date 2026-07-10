export function cronToDailyTime(cron: string | null | undefined): string {
  const parts = (cron || '').trim().split(/\s+/);
  if (parts.length !== 5 || parts[2] !== '*' || parts[3] !== '*' || parts[4] !== '*') return '07:00';
  const [minute, hour] = parts;
  if (!/^\d+$/.test(minute) || !/^\d+$/.test(hour)) return '07:00';
  return `${String(Math.min(23, Number(hour))).padStart(2, '0')}:${String(Math.min(59, Number(minute))).padStart(2, '0')}`;
}

export function dailyTimeToCron(time: string | null | undefined): string {
  const [hour = '7', minute = '0'] = (time || '07:00').split(':');
  return `${Number(minute)} ${Number(hour)} * * *`;
}
