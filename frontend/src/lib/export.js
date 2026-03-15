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

export function videoToTxt(video) {
  const lines = [];
  lines.push(`Cím: ${video.title || ''}`);
  lines.push(`URL: ${video.url || ''}`);
  if (video.uploaded_at) lines.push(`Feltöltve: ${formatDate(video.uploaded_at)}`);
  if (video.duration_seconds) lines.push(`Hossz: ${formatDuration(video.duration_seconds)}`);
  lines.push('');
  lines.push(video.transcript || '(nincs transzkript)');
  return lines.join('\n');
}

export function videoToMd(video) {
  const lines = [];
  lines.push(`# ${video.title || 'Ismeretlen cím'}`);
  lines.push('');
  if (video.url) lines.push(`**URL**: [${video.url}](${video.url})`);
  if (video.uploaded_at) lines.push(`**Feltöltve**: ${formatDate(video.uploaded_at)}`);
  if (video.duration_seconds) lines.push(`**Hossz**: ${formatDuration(video.duration_seconds)}`);
  lines.push('');
  lines.push(video.transcript || '*(nincs transzkript)*');
  return lines.join('\n');
}

export function channelToTxt(channelName, videos) {
  const parts = [`Csatorna: ${channelName}`, `Videók: ${videos.length}`, '', '='.repeat(60), ''];
  for (const video of videos) {
    parts.push(videoToTxt(video));
    parts.push('', '-'.repeat(60), '');
  }
  return parts.join('\n');
}

export function channelToMd(channelName, videos) {
  const parts = [`# Csatorna: ${channelName}`, '', `*${videos.length} videó*`, '', '---', ''];
  for (const video of videos) {
    parts.push(videoToMd(video));
    parts.push('', '---', '');
  }
  return parts.join('\n');
}

export function allChannelsToTxt(channelGroups) {
  const parts = [];
  for (const { channel, videos } of channelGroups) {
    parts.push(channelToTxt(channel.name || channel.channel_handle || 'Ismeretlen', videos));
    parts.push('\n' + '='.repeat(60) + '\n');
  }
  return parts.join('\n');
}

export function allChannelsToMd(channelGroups) {
  const parts = [];
  for (const { channel, videos } of channelGroups) {
    parts.push(channelToMd(channel.name || channel.channel_handle || 'Ismeretlen', videos));
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
