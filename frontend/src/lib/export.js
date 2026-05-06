/**
 * Client-side export utilities for generating TXT/MD files from transcript data.
 */

function formatDuration(seconds) {
  if (!seconds) return '';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${m}:${String(s).padStart(2, '0')}`;
}

function formatDate(iso) {
  if (!iso) return '';
  return new Date(iso).toLocaleDateString('hu-HU');
}

function isoDate(iso) {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return date.toISOString().slice(0, 10);
}

function transcriptForExport(video, timed = false) {
  return (timed ? video.transcript_timed : video.transcript) || video.transcript || '(nincs transzkript)';
}

function yamlString(value) {
  return `"${String(value || '').replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`;
}

function slug(value) {
  return String(value || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .substring(0, 60) || 'youtube';
}

function youtubeTimestampUrl(video, seconds) {
  if (!video.url || seconds == null) return '';
  const separator = video.url.includes('?') ? '&' : '?';
  return `${video.url}${separator}t=${seconds}s`;
}

function timeToSeconds(raw) {
  const parts = raw.split(':').map(part => Number(part.split('.')[0]));
  if (parts.some(Number.isNaN)) return null;
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  return null;
}

function obsidianTranscript(video, timed = true) {
  const transcript = transcriptForExport(video, timed);
  if (!timed) return transcript;

  return transcript.split('\n').map(line => {
    const rangeMatch = line.match(/^\s*\[(\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)\s*-->\s*[\d:.]+\]\s*(.+)$/);
    const simpleMatch = line.match(/^\s*\[?(\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)\]?\s+(.+)$/);
    const match = rangeMatch || simpleMatch;
    if (!match) return line;
    const [, time, text] = match;
    const seconds = timeToSeconds(time);
    const url = youtubeTimestampUrl(video, seconds);
    if (!url) return `- ${time} ${text}`;
    return `- [${time}](${url}) ${text}`;
  }).join('\n');
}

function channelName(channelOrName, fallback = 'Ismeretlen csatorna') {
  if (!channelOrName) return fallback;
  if (typeof channelOrName === 'string') return channelOrName;
  return channelOrName?.name || channelOrName?.channel_handle || fallback;
}

function videoChannelName(video, fallback = '') {
  if (video.channel?.name || video.channel?.channel_handle) return channelName(video.channel);
  if (video.channel_id?.name || video.channel_id?.channel_handle) return channelName(video.channel_id);
  return fallback;
}

function frontmatter(lines) {
  return ['---', ...lines.filter(Boolean), '---'].join('\n');
}

function listSection(title, items) {
  if (!Array.isArray(items) || items.length === 0) return [];
  return [`## ${title}`, '', ...items.map(item => `- ${item}`), ''];
}

export function videoToTxt(video, { timed = false } = {}) {
  const lines = [];
  lines.push(`Cím: ${video.title || ''}`);
  lines.push(`URL: ${video.url || ''}`);
  if (video.uploaded_at) lines.push(`Feltöltve: ${formatDate(video.uploaded_at)}`);
  if (video.duration_seconds) lines.push(`Hossz: ${formatDuration(video.duration_seconds)}`);
  if (timed) lines.push('Változat: időbélyeges');
  lines.push('');
  lines.push(transcriptForExport(video, timed));
  return lines.join('\n');
}

export function videoToMd(video, { timed = false } = {}) {
  const lines = [];
  lines.push(`# ${video.title || 'Ismeretlen cím'}`);
  lines.push('');
  if (video.url) lines.push(`**URL**: [${video.url}](${video.url})`);
  if (video.uploaded_at) lines.push(`**Feltöltve**: ${formatDate(video.uploaded_at)}`);
  if (video.duration_seconds) lines.push(`**Hossz**: ${formatDuration(video.duration_seconds)}`);
  if (timed) lines.push('**Változat**: időbélyeges');
  lines.push('');
  lines.push(transcriptForExport(video, timed));
  return lines.join('\n');
}

export function videoToObsidianMd(video, { channel = null, timed = true } = {}) {
  const title = video.title || 'Ismeretlen cím';
  const channelLabel = channelName(channel, '') || videoChannelName(video);
  const uploaded = isoDate(video.uploaded_at);
  const duration = formatDuration(video.duration_seconds);
  const tagChannel = channelLabel ? `  - youtube/channel/${slug(channelLabel)}` : '';
  const lines = [
    frontmatter([
      'type: youtube-video',
      'source: youtube',
      `title: ${yamlString(title)}`,
      channelLabel ? `channel: ${yamlString(channelLabel)}` : '',
      video.video_id ? `video_id: ${yamlString(video.video_id)}` : '',
      video.url ? `url: ${yamlString(video.url)}` : '',
      uploaded ? `uploaded: ${uploaded}` : '',
      duration ? `duration: ${yamlString(duration)}` : '',
      video.ai_notes_status ? `ai_notes_status: ${yamlString(video.ai_notes_status)}` : '',
      'tags:',
      '  - youtube',
      '  - youtube/transcript',
      tagChannel,
    ]),
    '',
    `# ${title}`,
    '',
    video.url ? `Forrás: [YouTube](${video.url})` : '',
    channelLabel ? `Csatorna: [[${channelLabel}]]` : '',
    uploaded ? `Feltöltve: ${uploaded}` : '',
    duration ? `Hossz: ${duration}` : '',
    '',
    video.summary ? '## AI összefoglaló' : '',
    video.summary ? '' : '',
    video.summary || '',
    video.summary ? '' : '',
    ...listSection('Témák', video.topics),
    ...listSection('Tanulságok', video.takeaways),
    ...listSection('Kérdések', video.questions),
    video.obsidian_note ? '## AI jegyzet' : '',
    video.obsidian_note ? '' : '',
    video.obsidian_note || '',
    video.obsidian_note ? '' : '',
    '## Saját jegyzetek',
    '',
    '- [ ] ',
    '',
    '## Transzkript',
    '',
    obsidianTranscript(video, timed),
  ];
  return lines.filter((line, index) => line !== '' || lines[index - 1] !== '').join('\n');
}

export function videoToMarkmapMd(video) {
  const title = video.title || 'Ismeretlen cím';
  const fm = '---\nmarkmap:\n  colorFreezeLevel: 2\n---';

  let body = (video.obsidian_note || '').trim();
  if (body) {
    if (!body.startsWith('# ')) body = `# ${title}\n${body}`;
  } else {
    const lines = [`# ${title}`];
    if (video.summary) {
      lines.push('## Summary');
      video.summary.split(/(?<=[.!?])\s+/).filter(Boolean).forEach(s => lines.push(`- ${s.trim()}`));
    }
    ['topics', 'takeaways', 'questions'].forEach(key => {
      if (video[key]?.length) {
        lines.push(`## ${key.charAt(0).toUpperCase() + key.slice(1)}`);
        video[key].forEach(t => lines.push(`- ${t}`));
      }
    });
    body = lines.join('\n');
  }
  return `${fm}\n\n${body}`;
}

export function markmapFilename(video, { channel = null } = {}) {
  const uploaded = isoDate(video.uploaded_at);
  const prefix = uploaded ? `${uploaded}_` : '';
  const channelPart = channel ? `${sanitizeFilename(channelName(channel))}_` : '';
  return `${prefix}${channelPart}${sanitizeFilename(video.title || video.video_id || 'video')}_mindmap.md`;
}

export function channelToTxt(channelName, videos, options = {}) {
  const parts = [`Csatorna: ${channelName}`, `Videók: ${videos.length}`, '', '='.repeat(60), ''];
  for (const video of videos) {
    parts.push(videoToTxt(video, options));
    parts.push('', '-'.repeat(60), '');
  }
  return parts.join('\n');
}

export function channelToMd(channelName, videos, options = {}) {
  const parts = [`# Csatorna: ${channelName}`, '', `*${videos.length} videó*`, '', '---', ''];
  for (const video of videos) {
    parts.push(videoToMd(video, options));
    parts.push('', '---', '');
  }
  return parts.join('\n');
}

export function channelToObsidianMd(channel, videos, options = {}) {
  const name = channelName(channel);
  const parts = [
    frontmatter([
      'type: youtube-channel',
      'source: youtube',
      `channel: ${yamlString(name)}`,
      `video_count: ${videos.length}`,
      'tags:',
      '  - youtube',
      '  - youtube/channel',
      `  - youtube/channel/${slug(name)}`,
    ]),
    '',
    `# ${name}`,
    '',
    `Videók: ${videos.length}`,
    '',
    '## Videók',
    '',
  ];

  for (const video of videos) {
    parts.push(videoToObsidianMd(video, { ...options, channel: name }));
    parts.push('');
    parts.push('---');
    parts.push('');
  }

  return parts.join('\n');
}

export function allChannelsToTxt(channelGroups, options = {}) {
  const parts = [];
  for (const { channel, videos } of channelGroups) {
    parts.push(channelToTxt(channel.name || channel.channel_handle || 'Ismeretlen', videos, options));
    parts.push('\n' + '='.repeat(60) + '\n');
  }
  return parts.join('\n');
}

export function allChannelsToMd(channelGroups, options = {}) {
  const parts = [];
  for (const { channel, videos } of channelGroups) {
    parts.push(channelToMd(channel.name || channel.channel_handle || 'Ismeretlen', videos, options));
  }
  return parts.join('\n');
}

export function allChannelsToObsidianMd(channelGroups, options = {}) {
  const totalVideos = channelGroups.reduce((sum, group) => sum + group.videos.length, 0);
  const parts = [
    frontmatter([
      'type: youtube-knowledge-base',
      'source: youtube',
      `channel_count: ${channelGroups.length}`,
      `video_count: ${totalVideos}`,
      'tags:',
      '  - youtube',
      '  - youtube/knowledge-base',
    ]),
    '',
    '# YouTube tudásbázis',
    '',
    `Csatornák: ${channelGroups.length}`,
    `Videók: ${totalVideos}`,
    '',
    '## Csatornák',
    '',
  ];

  for (const { channel, videos } of channelGroups) {
    parts.push(channelToObsidianMd(channel, videos, options));
    parts.push('');
    parts.push('---');
    parts.push('');
  }

  return parts.join('\n');
}

export function downloadFile(content, filename) {
  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function sanitizeFilename(name) {
  return (name || 'export').replace(/[^a-zA-Z0-9_\-\.]/g, '_').substring(0, 80);
}

export function obsidianFilename(video, { channel = null } = {}) {
  const uploaded = isoDate(video.uploaded_at);
  const prefix = uploaded ? `${uploaded}_` : '';
  const channelPart = channel ? `${sanitizeFilename(channelName(channel))}_` : '';
  return `${prefix}${channelPart}${sanitizeFilename(video.title || video.video_id || 'youtube-video')}.md`;
}
