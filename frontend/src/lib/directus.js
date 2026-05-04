const DIRECTUS_URL = '/admin';
const DIRECTUS_TOKEN = 'admin-token-change-me';

async function req(method, path, body) {
  const res = await fetch(`${DIRECTUS_URL}${path}`, {
    method,
    headers: {
      'Authorization': `Bearer ${DIRECTUS_TOKEN}`,
      'Content-Type': 'application/json',
    },
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

export async function updateChannel(id, data) {
  const result = await req('PATCH', `/items/channels/${id}`, data);
  return result?.data ?? {};
}

// ---- Videos (paginated) ----

const PAGE_SIZE = 100;
const VIDEO_FIELDS = [
  'id,video_id,title,url,uploaded_at,duration_seconds,status,transcript,transcript_timed,whisper_status',
  'summary,topics,takeaways,questions,obsidian_note,ai_notes_status,ai_notes_generated_at,ai_notes_error',
  'channel_id.id,channel_id.name,channel_id.channel_handle',
].join(',');

export async function getVideos(channelId, { sort = '-uploaded_at', page = 1, search = '' } = {}) {
  const params = new URLSearchParams({
    'filter[channel_id][_eq]': channelId,
    sort,
    limit: String(PAGE_SIZE),
    offset: String((page - 1) * PAGE_SIZE),
    'meta': 'filter_count',
    'fields': VIDEO_FIELDS,
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
    'fields': VIDEO_FIELDS,
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
    'fields': VIDEO_FIELDS,
  });
  const data = await req('GET', `/items/videos?${params}`);
  return data?.data ?? [];
}
