import type { FetcherStatus, WhisperStatus, Job, Schedule, AppSettings } from '../types.ts';

const FETCHER_URL = '/api';

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${FETCHER_URL}${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = '';
    try {
      const data = await res.json();
      detail = data.detail ? `: ${data.detail}` : '';
    } catch {}
    throw new Error(`${method} ${path} → ${res.status}${detail}`);
  }
  return res.status === 204 ? (null as T) : res.json();
}

interface FetchChannelsResult {
  queued: { url: string; action: 'refresh' | 'fetch'; id: string }[];
  count: number;
}

export function fetchChannels(urls: string[]): Promise<FetchChannelsResult> {
  return req('POST', '/fetch-channels', { urls });
}

export function fetchVideo(url: string, channelId: string | null = null): Promise<{ queued: true; url: string }> {
  return req('POST', '/fetch-video', { url, channel_id: channelId });
}

export function refreshChannel(channelId: string): Promise<{ queued: true; channel_id: string }> {
  return req('POST', `/refresh-channel/${channelId}`);
}

export function stopProcessing(queue?: string): Promise<unknown> {
  return req('POST', queue ? `/stop?queue=${queue}` : '/stop');
}

export function resumeProcessing(queue?: string): Promise<unknown> {
  return req('POST', queue ? `/resume?queue=${queue}` : '/resume');
}

export function getStatus(): Promise<FetcherStatus> {
  return req('GET', '/status');
}

export function getResources(): Promise<FetcherStatus['resources']> {
  return req('GET', '/resources');
}

export function openResourceStream(): EventSource {
  return new EventSource(`${FETCHER_URL}/resources/stream`);
}

export function getJobs(): Promise<{ jobs: Job[] }> {
  return req('GET', '/jobs');
}

function jobAction(jobId: string, action: string, body: unknown = null): Promise<unknown> {
  return req('POST', `/jobs/${jobId}/${action}`, body);
}

export function pauseJob(jobId: string): Promise<unknown> {
  return jobAction(jobId, 'pause');
}

export function resumeJob(jobId: string): Promise<unknown> {
  return jobAction(jobId, 'resume');
}

export function startJob(jobId: string): Promise<unknown> {
  return jobAction(jobId, 'start');
}

export function moveJob(jobId: string, direction: 'up' | 'down'): Promise<unknown> {
  return jobAction(jobId, 'move', { direction });
}

export function deleteJob(jobId: string): Promise<unknown> {
  return req('DELETE', `/jobs/${jobId}`);
}

export function refreshDates(): Promise<unknown> {
  return req('POST', '/refresh-dates');
}

export function refreshThumbnails(): Promise<unknown> {
  return req('POST', '/refresh-thumbnails');
}

export function refreshVideoThumbnail(videoId: string): Promise<{ thumbnail_url: string | null }> {
  return req('POST', `/refresh-thumbnail/${videoId}`);
}

type GenerateAiNotesResult =
  | { queued: false; existing: true; job_id: string }
  | { queued: true; limit: number; job_id: string };

export function generateAiNotes(limit?: number): Promise<GenerateAiNotesResult> {
  return req('POST', '/ai-notes', limit === undefined ? {} : { limit });
}

interface ChannelAiNotesResult {
  queued: true;
  channel_id: string;
  count: number;
  skipped_active: number;
  limit: number;
  items: { video_id: string; title: string | null; job_id: string }[];
}

export function generateAiNotesForChannel(channelId: string, limit = 500): Promise<ChannelAiNotesResult> {
  return req('POST', `/channels/${channelId}/ai-notes`, { limit });
}

export function generateQuickNoteForVideo(videoId: string): Promise<unknown> {
  return req('POST', `/quick-notes/${videoId}`);
}

export function generateAiNoteForVideo(videoId: string): Promise<unknown> {
  return req('POST', `/ai-notes/${videoId}`);
}

export function regenerateAiNoteFields(videoId: string, fields: string[]): Promise<unknown> {
  return req('POST', `/ai-notes/${videoId}/regenerate`, { fields });
}

export function deleteAiNoteForVideo(videoId: string): Promise<unknown> {
  return req('DELETE', `/ai-notes/${videoId}`);
}

export function getSchedule(): Promise<Schedule> {
  return req('GET', '/schedule');
}

export function updateSchedule(cron: string, timezone: string): Promise<Schedule> {
  return req('PATCH', '/schedule', { cron, timezone });
}

export function getAppSettings(): Promise<Partial<AppSettings>> {
  return req('GET', '/settings');
}

export function updateAppSettings(settings: Partial<AppSettings>): Promise<unknown> {
  return req('PATCH', '/settings', settings);
}

// ---- Whisper service ----

const WHISPER_URL = '/whisper';

export async function getWhisperStatus(): Promise<WhisperStatus> {
  const res = await fetch(`${WHISPER_URL}/status`);
  if (!res.ok) throw new Error(`whisper status → ${res.status}`);
  return res.json();
}

export async function startWhisperBatch(limit = 50): Promise<unknown> {
  const res = await fetch(`${WHISPER_URL}/transcribe-batch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ limit }),
  });
  if (!res.ok) throw new Error(`whisper batch → ${res.status}`);
  return res.json();
}

export async function stopWhisper(): Promise<unknown> {
  const res = await fetch(`${WHISPER_URL}/stop`, { method: 'POST' });
  if (!res.ok) throw new Error(`whisper stop → ${res.status}`);
  return res.json();
}

export async function resumeWhisper(): Promise<unknown> {
  const res = await fetch(`${WHISPER_URL}/resume`, { method: 'POST' });
  if (!res.ok) throw new Error(`whisper resume → ${res.status}`);
  return res.json();
}
