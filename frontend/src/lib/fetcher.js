const FETCHER_URL = '/api';

async function req(method, path, body) {
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
  return res.status === 204 ? null : res.json();
}

export function fetchChannels(urls) {
  return req('POST', '/fetch-channels', { urls });
}

export function fetchVideo(url, channelId = null) {
  return req('POST', '/fetch-video', { url, channel_id: channelId });
}

export function refreshChannel(channelId) {
  return req('POST', `/refresh-channel/${channelId}`);
}

export function stopProcessing(queue) {
  return req('POST', queue ? `/stop?queue=${queue}` : '/stop');
}

export function resumeProcessing(queue) {
  return req('POST', queue ? `/resume?queue=${queue}` : '/resume');
}

export function getStatus() {
  return req('GET', '/status');
}

export function getResources() {
  return req('GET', '/resources');
}

export function openResourceStream() {
  return new EventSource(`${FETCHER_URL}/resources/stream`);
}

export function getJobs() {
  return req('GET', '/jobs');
}

function jobAction(jobId, action, body = null) {
  return req('POST', `/jobs/${jobId}/${action}`, body);
}

export function pauseJob(jobId) {
  return jobAction(jobId, 'pause');
}

export function resumeJob(jobId) {
  return jobAction(jobId, 'resume');
}

export function startJob(jobId) {
  return jobAction(jobId, 'start');
}

export function moveJob(jobId, direction) {
  return jobAction(jobId, 'move', { direction });
}

export function deleteJob(jobId) {
  return req('DELETE', `/jobs/${jobId}`);
}

export function refreshDates() {
  return req('POST', '/refresh-dates');
}

export function refreshThumbnails() {
  return req('POST', '/refresh-thumbnails');
}

export function generateAiNotes(limit) {
  return req('POST', '/ai-notes', limit === undefined ? {} : { limit });
}

export function generateAiNotesForChannel(channelId, limit = 500) {
  return req('POST', `/channels/${channelId}/ai-notes`, { limit });
}

export function generateQuickNoteForVideo(videoId) {
  return req('POST', `/quick-notes/${videoId}`);
}

export function generateAiNoteForVideo(videoId) {
  return req('POST', `/ai-notes/${videoId}`);
}

export function regenerateAiNoteFields(videoId, fields) {
  return req('POST', `/ai-notes/${videoId}/regenerate`, { fields });
}

export function deleteAiNoteForVideo(videoId) {
  return req('DELETE', `/ai-notes/${videoId}`);
}

export function getSchedule() {
  return req('GET', '/schedule');
}

export function updateSchedule(cron, timezone) {
  return req('PATCH', '/schedule', { cron, timezone });
}

export function getAppSettings() {
  return req('GET', '/settings');
}

export function updateAppSettings(settings) {
  return req('PATCH', '/settings', settings);
}

// ---- Whisper service ----

const WHISPER_URL = '/whisper';

export async function getWhisperStatus() {
  const res = await fetch(`${WHISPER_URL}/status`);
  if (!res.ok) throw new Error(`whisper status → ${res.status}`);
  return res.json();
}

export async function startWhisperBatch(limit = 50) {
  const res = await fetch(`${WHISPER_URL}/transcribe-batch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ limit }),
  });
  if (!res.ok) throw new Error(`whisper batch → ${res.status}`);
  return res.json();
}

export async function stopWhisper() {
  const res = await fetch(`${WHISPER_URL}/stop`, { method: 'POST' });
  if (!res.ok) throw new Error(`whisper stop → ${res.status}`);
  return res.json();
}

export async function resumeWhisper() {
  const res = await fetch(`${WHISPER_URL}/resume`, { method: 'POST' });
  if (!res.ok) throw new Error(`whisper resume → ${res.status}`);
  return res.json();
}
