const API_URL = '/api';

async function req(method, path, body) {
  const res = await fetch(`${API_URL}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${method} ${path} -> ${res.status}`);
  return res.status === 204 ? null : res.json();
}

function paramsFrom(values) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== null && value !== '') {
      params.set(key, String(value));
    }
  }
  return params.toString();
}

// ---- Channels ----

export async function getChannels() {
  return req('GET', '/ui/channels');
}

export async function deleteChannel(id) {
  return req('DELETE', `/ui/channels/${id}`);
}

export async function updateChannel(id, data) {
  return req('PATCH', `/ui/channels/${id}`, data);
}

// ---- Videos ----

export async function getVideos(channelId, opts = {}) {
  const query = paramsFrom({
    channel_id: channelId,
    sort: opts.sort || '-uploaded_at',
    page: opts.page || 1,
    search: opts.search || '',
    status_filter: opts.statusFilter || 'all',
    ai_filter: opts.aiFilter || 'all',
    members_filter: opts.membersFilter || 'all',
  });
  return req('GET', `/ui/videos?${query}`);
}

export async function getAllVideos(opts = {}) {
  const query = paramsFrom({
    sort: opts.sort || '-uploaded_at',
    page: opts.page || 1,
    search: opts.search || '',
    status_filter: opts.statusFilter || 'all',
    ai_filter: opts.aiFilter || 'all',
    members_filter: opts.membersFilter || 'all',
  });
  return req('GET', `/ui/videos?${query}`);
}

export async function getDailyVideos(dateValue, tz) {
  const params = { date: dateValue };
  if (tz) params.tz = tz;
  return req('GET', `/ui/videos/daily?${paramsFrom(params)}`);
}

export async function getTotalVideoCount() {
  const data = await req('GET', '/ui/videos/count');
  return data?.count ?? 0;
}

export async function getAdminStats() {
  return req('GET', '/ui/admin-stats');
}

export async function getChannelCoverage() {
  const data = await req('GET', '/ui/channel-coverage');
  const toMap = rows => new Map((rows ?? []).map(row => [row.channel_id, Number(row.count?.id || 0)]));
  return {
    totalMap: toMap(data?.total),
    transcriptMap: toMap(data?.transcriptDone),
    aiMap: toMap(data?.aiDone),
  };
}

export async function getMonthlyVideoCounts() {
  return req('GET', '/ui/monthly-video-counts');
}

export async function getErrorVideos() {
  return req('GET', '/ui/error-videos');
}

export async function updateVideoFields(id, fields) {
  return req('PATCH', `/ui/videos/${id}`, fields);
}

export async function getAllChannelVideos(channelId, { sort = '-uploaded_at' } = {}) {
  return req('GET', `/ui/channels/${channelId}/videos?${paramsFrom({ sort })}`);
}
