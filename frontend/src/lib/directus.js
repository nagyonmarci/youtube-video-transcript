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
  const channels = data?.data ?? [];
  const countData = await req(
    'GET',
    '/items/videos?aggregate[count]=id&groupBy[]=channel_id&limit=-1'
  );
  const counts = new Map(
    (countData?.data ?? [])
      .filter(row => row.channel_id)
      .map(row => [row.channel_id, Number(row.count?.id || 0)])
  );
  return channels.map(ch => ({
    ...ch,
    video_count: counts.get(ch.id) ?? 0,
  }));
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
  'id,video_id,title,url,thumbnail_url,uploaded_at,duration_seconds,status,is_members_only,transcript,transcript_timed,whisper_status',
  'summary,topics,takeaways,questions,obsidian_note,study_guide,critique,ai_notes_status,ai_notes_generated_at,ai_notes_error',
  'channel_id.id,channel_id.name,channel_id.channel_handle',
].join(',');

function applyVideoFilters(params, { search, statusFilter, aiFilter, membersFilter }) {
  if (search) {
    params.set('filter[title][_icontains]', search);
  }
  if (statusFilter && statusFilter !== 'all') {
    params.set('filter[status][_eq]', statusFilter);
  }
  if (aiFilter === 'done') {
    params.set('filter[ai_notes_status][_eq]', 'done');
  } else if (aiFilter === 'missing') {
    params.set('filter[_and][0][transcript][_nnull]', 'true');
    params.set('filter[_and][1][summary][_null]', 'true');
  } else if (aiFilter === 'error') {
    params.set('filter[ai_notes_status][_eq]', 'error');
  }
  if (membersFilter === 'hide') {
    params.set('filter[_or][0][is_members_only][_neq]', 'true');
    params.set('filter[_or][1][is_members_only][_null]', 'true');
  } else if (membersFilter === 'only') {
    params.set('filter[is_members_only][_eq]', 'true');
  }
}

export async function getVideos(channelId, { sort = '-uploaded_at', page = 1, search = '', statusFilter = 'all', aiFilter = 'all', membersFilter = 'all' } = {}) {
  const params = new URLSearchParams({
    'filter[channel_id][_eq]': channelId,
    sort,
    limit: String(PAGE_SIZE),
    offset: String((page - 1) * PAGE_SIZE),
    'meta': 'filter_count',
    'fields': VIDEO_FIELDS,
  });
  applyVideoFilters(params, { search, statusFilter, aiFilter, membersFilter });
  const data = await req('GET', `/items/videos?${params}`);
  return { items: data?.data ?? [], total: data?.meta?.filter_count ?? 0 };
}

export async function getAllVideos({ sort = '-uploaded_at', page = 1, search = '', statusFilter = 'all', aiFilter = 'all', membersFilter = 'all' } = {}) {
  const params = new URLSearchParams({
    sort,
    limit: String(PAGE_SIZE),
    offset: String((page - 1) * PAGE_SIZE),
    'meta': 'filter_count',
    'fields': VIDEO_FIELDS,
  });
  applyVideoFilters(params, { search, statusFilter, aiFilter, membersFilter });
  const data = await req('GET', `/items/videos?${params}`);
  return { items: data?.data ?? [], total: data?.meta?.filter_count ?? 0 };
}

export async function getDailyVideos(dateValue) {
  const start = new Date(`${dateValue}T00:00:00`);
  const end = new Date(start);
  end.setDate(end.getDate() + 1);

  const params = new URLSearchParams({
    'filter[uploaded_at][_gte]': start.toISOString(),
    'filter[uploaded_at][_lt]': end.toISOString(),
    sort: '-uploaded_at',
    limit: '-1',
    'fields': VIDEO_FIELDS,
  });
  const data = await req('GET', `/items/videos?${params}`);
  return data?.data ?? [];
}

async function countVideos(extraParams = {}) {
  const params = new URLSearchParams({
    limit: '1',
    'meta': 'filter_count',
    'fields': 'id',
    ...extraParams,
  });
  const data = await req('GET', `/items/videos?${params}`);
  return data?.meta?.filter_count ?? 0;
}

export function getTotalVideoCount() {
  return countVideos();
}

export async function getAdminStats() {
  const today = new Date();
  const dateValue = [
    today.getFullYear(),
    String(today.getMonth() + 1).padStart(2, '0'),
    String(today.getDate()).padStart(2, '0'),
  ].join('-');
  const start = new Date(`${dateValue}T00:00:00`);
  const end = new Date(start);
  end.setDate(end.getDate() + 1);

  const [
    totalVideos,
    todayVideos,
    errorVideos,
    missingTranscripts,
    missingAiNotes,
  ] = await Promise.all([
    countVideos(),
    countVideos({
      'filter[uploaded_at][_gte]': start.toISOString(),
      'filter[uploaded_at][_lt]': end.toISOString(),
    }),
    countVideos({ 'filter[status][_eq]': 'error' }),
    countVideos({
      'filter[_or][0][transcript][_null]': 'true',
      'filter[_or][1][status][_in]': 'pending,no_transcript,error',
    }),
    countVideos({
      'filter[_and][0][transcript][_nnull]': 'true',
      'filter[_and][1][_or][0][summary][_null]': 'true',
      'filter[_and][1][_or][1][critique][_null]': 'true',
    }),
  ]);

  return { totalVideos, todayVideos, errorVideos, missingTranscripts, missingAiNotes };
}

export async function getChannelCoverage() {
  const [total, transcriptDone, aiDone] = await Promise.all([
    req('GET', '/items/videos?aggregate[count]=id&groupBy[]=channel_id&limit=-1'),
    req('GET', '/items/videos?filter[status][_eq]=done&aggregate[count]=id&groupBy[]=channel_id&limit=-1'),
    req('GET', '/items/videos?filter[ai_notes_status][_eq]=done&aggregate[count]=id&groupBy[]=channel_id&limit=-1'),
  ]);
  const totalMap = new Map((total?.data ?? []).map(r => [r.channel_id, Number(r.count?.id || 0)]));
  const transcriptMap = new Map((transcriptDone?.data ?? []).map(r => [r.channel_id, Number(r.count?.id || 0)]));
  const aiMap = new Map((aiDone?.data ?? []).map(r => [r.channel_id, Number(r.count?.id || 0)]));
  return { totalMap, transcriptMap, aiMap };
}

export async function getMonthlyVideoCounts() {
  const cutoff = new Date();
  cutoff.setMonth(cutoff.getMonth() - 11);
  cutoff.setDate(1);
  const params = new URLSearchParams({
    'filter[uploaded_at][_gte]': cutoff.toISOString(),
    'fields': 'uploaded_at',
    'limit': '-1',
  });
  const data = await req('GET', `/items/videos?${params}`);
  const counts = {};
  for (const v of data?.data ?? []) {
    if (!v.uploaded_at) continue;
    const month = v.uploaded_at.slice(0, 7);
    counts[month] = (counts[month] || 0) + 1;
  }
  // Fill all 12 months even if count is 0
  const result = [];
  for (let i = 11; i >= 0; i--) {
    const d = new Date();
    d.setMonth(d.getMonth() - i);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    result.push({ month: key, count: counts[key] || 0 });
  }
  return result;
}

export async function getErrorVideos() {
  const params = new URLSearchParams({
    'filter[status][_eq]': 'error',
    'fields': 'id,video_id,title,url,channel_id.name,channel_id.channel_handle',
    'sort': '-processed_at',
    'limit': '50',
  });
  const data = await req('GET', `/items/videos?${params}`);
  return data?.data ?? [];
}

export async function updateVideoFields(id, fields) {
  const result = await req('PATCH', `/items/videos/${id}`, fields);
  return result?.data ?? {};
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
