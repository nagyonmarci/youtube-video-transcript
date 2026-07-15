import type {
  Channel,
  Video,
  PaginatedVideos,
  ErrorVideoSummary,
  AdminStats,
  MonthlyVideoCount,
  ChannelCoverageMaps,
} from '../types.ts';
import { createRequester } from './httpClient.ts';

const API_URL = '/api';

const req = createRequester(API_URL);

function paramsFrom(values: Record<string, unknown>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== null && value !== '') {
      params.set(key, String(value));
    }
  }
  return params.toString();
}

interface VideoListOpts {
  sort?: string;
  page?: number;
  search?: string;
  statusFilter?: string;
  aiFilter?: string;
  membersFilter?: string;
}

// ---- Channels ----

export async function getChannels(): Promise<Channel[]> {
  return req('GET', '/ui/channels');
}

export async function deleteChannel(id: string): Promise<{ deleted: true; id: string }> {
  return req('DELETE', `/ui/channels/${id}`);
}

export async function updateChannel(id: string, data: Partial<Channel>): Promise<Channel> {
  return req('PATCH', `/ui/channels/${id}`, data);
}

// ---- Videos ----

export async function getVideos(channelId: string, opts: VideoListOpts = {}): Promise<PaginatedVideos> {
  const query = paramsFrom({
    channel_id: channelId,
    sort: opts.sort || '-uploaded_at',
    page: opts.page || 1,
    search: opts.search || '',
    status_filter: opts.statusFilter || 'all',
    ai_filter: opts.aiFilter || 'all',
    members_filter: opts.membersFilter || 'hide',
  });
  return req('GET', `/ui/videos?${query}`);
}

export async function getAllVideos(opts: VideoListOpts = {}): Promise<PaginatedVideos> {
  const query = paramsFrom({
    sort: opts.sort || '-uploaded_at',
    page: opts.page || 1,
    search: opts.search || '',
    status_filter: opts.statusFilter || 'all',
    ai_filter: opts.aiFilter || 'all',
    members_filter: opts.membersFilter || 'hide',
  });
  return req('GET', `/ui/videos?${query}`);
}

export async function getSearchResults(query: string, opts: VideoListOpts = {}): Promise<PaginatedVideos> {
  const params = paramsFrom({
    q: query,
    page: opts.page || 1,
    status_filter: opts.statusFilter || 'all',
    ai_filter: opts.aiFilter || 'all',
    members_filter: opts.membersFilter || 'hide',
  });
  return req('GET', `/ui/search?${params}`);
}

export async function getVideosInRange(dateFrom: string, dateTo: string, tz?: string): Promise<Video[]> {
  const params: Record<string, unknown> = { date_from: dateFrom, date_to: dateTo };
  if (tz) params.tz = tz;
  return req('GET', `/ui/videos/range?${paramsFrom(params)}`);
}

export async function getTotalVideoCount(): Promise<number> {
  const data = await req<{ count?: number }>('GET', '/ui/videos/count');
  return data?.count ?? 0;
}

export async function getAdminStats(): Promise<AdminStats> {
  return req('GET', '/ui/admin-stats');
}

interface CoverageRow {
  channel_id: string;
  count?: { id?: number };
}

interface ChannelCoverageResponse {
  total?: CoverageRow[];
  transcriptDone?: CoverageRow[];
  aiDone?: CoverageRow[];
}

export async function getChannelCoverage(): Promise<ChannelCoverageMaps> {
  const data = await req<ChannelCoverageResponse>('GET', '/ui/channel-coverage');
  const toMap = (rows?: CoverageRow[]) => new Map((rows ?? []).map(row => [row.channel_id, Number(row.count?.id || 0)]));
  return {
    totalMap: toMap(data?.total),
    transcriptMap: toMap(data?.transcriptDone),
    aiMap: toMap(data?.aiDone),
  };
}

export async function getMonthlyVideoCounts(): Promise<MonthlyVideoCount[]> {
  return req('GET', '/ui/monthly-video-counts');
}

export async function getErrorVideos(): Promise<ErrorVideoSummary[]> {
  return req('GET', '/ui/error-videos');
}

export async function updateVideoFields(id: string, fields: Partial<Video>): Promise<Video> {
  return req('PATCH', `/ui/videos/${id}`, fields);
}

export async function getAllChannelVideos(channelId: string, { sort = '-uploaded_at' }: { sort?: string } = {}): Promise<Video[]> {
  return req('GET', `/ui/channels/${channelId}/videos?${paramsFrom({ sort })}`);
}
