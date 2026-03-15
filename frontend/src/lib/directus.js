const DIRECTUS_URL = import.meta.env.PUBLIC_DIRECTUS_URL || 'http://localhost:8055';
const DIRECTUS_TOKEN = import.meta.env.PUBLIC_DIRECTUS_TOKEN || 'admin-token-change-me';

const headers = {
  'Authorization': `Bearer ${DIRECTUS_TOKEN}`,
  'Content-Type': 'application/json',
};

async function req(method, path, body) {
  const res = await fetch(`${DIRECTUS_URL}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${method} ${path} → ${res.status}`);
  return res.status === 204 ? null : res.json();
}

// ---- Channels ----

export async function getChannels() {
  const data = await req('GET', '/items/channels?sort[]=-added_at&limit=-1');
  return data?.data ?? [];
}

export async function deleteChannel(id) {
  return req('DELETE', `/items/channels/${id}`);
}

// ---- Videos ----

export async function getVideos(channelId, { sort = '-uploaded_at' } = {}) {
  const params = new URLSearchParams({
    'filter[channel_id][_eq]': channelId,
    sort,
    limit: '-1',
  });
  const data = await req('GET', `/items/videos?${params}`);
  return data?.data ?? [];
}

export async function getAllVideos({ sort = '-uploaded_at' } = {}) {
  const params = new URLSearchParams({ sort, limit: '-1' });
  const data = await req('GET', `/items/videos?${params}`);
  return data?.data ?? [];
}
