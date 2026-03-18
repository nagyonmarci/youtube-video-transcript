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

// ---- Videos (paginated) ----

const PAGE_SIZE = 100;

export async function getVideos(channelId, { sort = '-uploaded_at', page = 1, search = '' } = {}) {
  const params = new URLSearchParams({
    'filter[channel_id][_eq]': channelId,
    sort,
    limit: String(PAGE_SIZE),
    offset: String((page - 1) * PAGE_SIZE),
    'meta': 'filter_count',
    'fields': 'id,video_id,title,url,uploaded_at,duration_seconds,status,transcript,whisper_status',
  });
  if (search) {
    params.set('filter[title][_icontains]', search);
  }
  const data = await req('GET', `/items/videos?${params}`);
  return { items: data?.data ?? [], total: data?.meta?.filter_count ?? 0 };
}

export async function getAllVideos({ sort = '-uploaded_at', page = 1, search = '' } = {}) {
  const params = new URLSearchParams({
    sort,
    limit: String(PAGE_SIZE),
    offset: String((page - 1) * PAGE_SIZE),
    'meta': 'filter_count',
    'fields': 'id,video_id,title,url,uploaded_at,duration_seconds,status,transcript,whisper_status',
  });
  if (search) {
    params.set('filter[title][_icontains]', search);
  }
  const data = await req('GET', `/items/videos?${params}`);
  return { items: data?.data ?? [], total: data?.meta?.filter_count ?? 0 };
}

// Non-paginated fetch for export (all videos for a channel)
export async function getAllChannelVideos(channelId, { sort = '-uploaded_at' } = {}) {
  const params = new URLSearchParams({
    'filter[channel_id][_eq]': channelId,
    sort,
    limit: '-1',
  });
  const data = await req('GET', `/items/videos?${params}`);
  return data?.data ?? [];
}
