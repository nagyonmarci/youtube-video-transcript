const FETCHER_URL = '/api';

export async function fetchChannels(urls) {
  const res = await fetch(`${FETCHER_URL}/fetch-channels`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ urls }),
  });
  if (!res.ok) throw new Error(`fetch-channels → ${res.status}`);
  return res.json();
}

export async function fetchVideo(url, channelId = null) {
  const res = await fetch(`${FETCHER_URL}/fetch-video`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, channel_id: channelId }),
  });
  if (!res.ok) throw new Error(`fetch-video → ${res.status}`);
  return res.json();
}

export async function refreshChannel(channelId) {
  const res = await fetch(`${FETCHER_URL}/refresh-channel/${channelId}`, {
    method: 'POST',
  });
  if (!res.ok) throw new Error(`refresh-channel → ${res.status}`);
  return res.json();
}

export async function stopProcessing(queue) {
  const url = queue ? `${FETCHER_URL}/stop?queue=${queue}` : `${FETCHER_URL}/stop`;
  const res = await fetch(url, { method: 'POST' });
  if (!res.ok) throw new Error(`stop → ${res.status}`);
  return res.json();
}

export async function getStatus() {
  const res = await fetch(`${FETCHER_URL}/status`);
  if (!res.ok) throw new Error(`status → ${res.status}`);
  return res.json();
}

export async function getResources() {
  const res = await fetch(`${FETCHER_URL}/resources`);
  if (!res.ok) throw new Error(`resources → ${res.status}`);
  return res.json();
}

export async function getJobs() {
  const res = await fetch(`${FETCHER_URL}/jobs`);
  if (!res.ok) throw new Error(`jobs → ${res.status}`);
  return res.json();
}

async function jobAction(jobId, action, body = null) {
  const res = await fetch(`${FETCHER_URL}/jobs/${jobId}/${action}`, {
    method: 'POST',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = '';
    try {
      const data = await res.json();
      detail = data.detail ? `: ${data.detail}` : '';
    } catch {}
    throw new Error(`jobs/${jobId}/${action} → ${res.status}${detail}`);
  }
  return res.json();
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

export async function deleteJob(jobId) {
  const res = await fetch(`${FETCHER_URL}/jobs/${jobId}`, { method: 'DELETE' });
  if (!res.ok) {
    let detail = '';
    try {
      const data = await res.json();
      detail = data.detail ? `: ${data.detail}` : '';
    } catch {}
    throw new Error(`jobs/${jobId} → ${res.status}${detail}`);
  }
  return res.json();
}

export async function refreshDates() {
  const res = await fetch(`${FETCHER_URL}/refresh-dates`, { method: 'POST' });
  if (!res.ok) throw new Error(`refresh-dates → ${res.status}`);
  return res.json();
}

export async function refreshThumbnails() {
  const res = await fetch(`${FETCHER_URL}/refresh-thumbnails`, { method: 'POST' });
  if (!res.ok) throw new Error(`refresh-thumbnails → ${res.status}`);
  return res.json();
}

export async function generateAiNotes(limit) {
  const res = await fetch(`${FETCHER_URL}/ai-notes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(limit === undefined ? {} : { limit }),
  });
  if (!res.ok) throw new Error(`ai-notes → ${res.status}`);
  return res.json();
}

export async function generateAiNotesForChannel(channelId, limit = 500) {
  const res = await fetch(`${FETCHER_URL}/channels/${channelId}/ai-notes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ limit }),
  });
  if (!res.ok) {
    let detail = '';
    try {
      const data = await res.json();
      detail = data.detail ? `: ${data.detail}` : '';
    } catch {}
    throw new Error(`channels/${channelId}/ai-notes → ${res.status}${detail}`);
  }
  return res.json();
}

export async function generateAiNoteForVideo(videoId) {
  const res = await fetch(`${FETCHER_URL}/ai-notes/${videoId}`, { method: 'POST' });
  if (!res.ok) {
    let detail = '';
    try {
      const data = await res.json();
      detail = data.detail ? `: ${data.detail}` : '';
    } catch {}
    throw new Error(`ai-notes/${videoId} → ${res.status}${detail}`);
  }
  return res.json();
}

export async function regenerateAiNoteFields(videoId, fields) {
  const res = await fetch(`${FETCHER_URL}/ai-notes/${videoId}/regenerate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fields }),
  });
  if (!res.ok) {
    let detail = '';
    try {
      const data = await res.json();
      detail = data.detail ? `: ${data.detail}` : '';
    } catch {}
    throw new Error(`ai-notes/${videoId}/regenerate → ${res.status}${detail}`);
  }
  return res.json();
}

export async function deleteAiNoteForVideo(videoId) {
  const res = await fetch(`${FETCHER_URL}/ai-notes/${videoId}`, { method: 'DELETE' });
  if (!res.ok) {
    let detail = '';
    try {
      const data = await res.json();
      detail = data.detail ? `: ${data.detail}` : '';
    } catch {}
    throw new Error(`delete ai-notes/${videoId} → ${res.status}${detail}`);
  }
  return res.json();
}

export async function getSchedule() {
  const res = await fetch(`${FETCHER_URL}/schedule`);
  if (!res.ok) throw new Error(`schedule → ${res.status}`);
  return res.json();
}

export async function updateSchedule(cron, timezone) {
  const res = await fetch(`${FETCHER_URL}/schedule`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ cron, timezone }),
  });
  if (!res.ok) {
    let detail = '';
    try {
      const data = await res.json();
      detail = data.detail ? `: ${data.detail}` : '';
    } catch {}
    throw new Error(`schedule → ${res.status}${detail}`);
  }
  return res.json();
}

export async function getAppSettings() {
  const res = await fetch(`${FETCHER_URL}/settings`);
  if (!res.ok) throw new Error(`settings → ${res.status}`);
  return res.json();
}

export async function updateAppSettings(settings) {
  const res = await fetch(`${FETCHER_URL}/settings`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings),
  });
  if (!res.ok) {
    let detail = '';
    try {
      const data = await res.json();
      detail = data.detail ? `: ${data.detail}` : '';
    } catch {}
    throw new Error(`settings → ${res.status}${detail}`);
  }
  return res.json();
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
