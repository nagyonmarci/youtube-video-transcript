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

export async function stopProcessing() {
  const res = await fetch(`${FETCHER_URL}/stop`, { method: 'POST' });
  if (!res.ok) throw new Error(`stop → ${res.status}`);
  return res.json();
}

export async function getStatus() {
  const res = await fetch(`${FETCHER_URL}/status`);
  if (!res.ok) throw new Error(`status → ${res.status}`);
  return res.json();
}

export async function refreshDates() {
  const res = await fetch(`${FETCHER_URL}/refresh-dates`, { method: 'POST' });
  if (!res.ok) throw new Error(`refresh-dates → ${res.status}`);
  return res.json();
}

export async function generateAiNotes(limit = 10) {
  const res = await fetch(`${FETCHER_URL}/ai-notes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ limit }),
  });
  if (!res.ok) throw new Error(`ai-notes → ${res.status}`);
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
