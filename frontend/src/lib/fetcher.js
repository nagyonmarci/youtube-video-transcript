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
