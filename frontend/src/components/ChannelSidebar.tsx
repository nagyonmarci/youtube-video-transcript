import { useState, useRef, type FormEvent, type ChangeEvent } from 'react';
import { deleteChannel, getAllChannelVideos } from '../lib/directus.ts';
import { fetchChannels, fetchVideo, refreshChannel } from '../lib/fetcher.ts';
import {
  channelToTxt, channelToMd, channelToObsidianMd, allChannelsToTxt, allChannelsToMd, allChannelsToObsidianMd,
  downloadFile, sanitizeFilename,
} from '../lib/export.ts';
import { useT } from '../lib/i18n.tsx';
import { parseChannelFile } from '../lib/channelUtils.ts';
import { useMessage } from '../lib/useMessage.ts';
import type { Channel, Video } from '../types.ts';

interface ChannelSidebarProps {
  channels: Channel[];
  selectedChannel: Channel | null;
  onSelect: (ch: Channel | null) => void;
  onChannelsChanged: () => void;
  videos: Video[];
}

export default function ChannelSidebar({ channels, selectedChannel, onSelect, onChannelsChanged, videos }: ChannelSidebarProps) {
  const { t } = useT();
  const { msg, showMsg } = useMessage();
  const [channelInput, setChannelInput] = useState('');
  const [videoInput, setVideoInput] = useState('');
  const [busy, setBusy] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const STATUS_LABEL: Record<string, string> = {
    pending: t('status.pending'),
    processing: t('status.inProgress'),
    done: t('status.done'),
    error: t('status.error'),
  };

  async function addChannels(urls: string[]) {
    if (!urls.length) return;
    setBusy(true);
    try {
      const result = await fetchChannels(urls);
      showMsg(t('msg.channelQueued', { count: result.count }));
      onChannelsChanged();
    } catch (e) {
      showMsg(t('msg.errGeneric', { error: (e as Error).message }), true);
    } finally {
      setBusy(false);
    }
  }

  async function handleChannelSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const urls = channelInput.split('\n').map(l => l.trim()).filter(Boolean);
    await addChannels(urls);
    setChannelInput('');
  }

  async function handleVideoSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const url = videoInput.trim();
    if (!url) return;
    setBusy(true);
    try {
      await fetchVideo(url, selectedChannel?.id ?? null);
      showMsg(t('msg.videoQueued'));
      setVideoInput('');
    } catch (e) {
      showMsg(t('msg.errGeneric', { error: (e as Error).message }), true);
    } finally {
      setBusy(false);
    }
  }

  async function handleFileUpload(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const text = await file.text();
    const urls = parseChannelFile(text);
    e.target.value = '';
    await addChannels(urls);
  }

  async function handleDelete(ch: Channel) {
    if (!confirm(t('confirm.deleteChannel', { name: ch.name || ch.channel_handle }))) return;
    await deleteChannel(ch.id);
    if (selectedChannel?.id === ch.id) onSelect(null);
    onChannelsChanged();
  }

  async function handleRefresh(ch: Channel) {
    setBusy(true);
    try {
      await refreshChannel(ch.id);
      showMsg(t('msg.refreshQueued'));
    } catch (e) {
      showMsg(t('msg.errGeneric', { error: (e as Error).message }), true);
    } finally {
      setBusy(false);
    }
  }

  async function handleExportChannel(ch: Channel, fmt: 'txt' | 'md' | 'obsidian', timed = false) {
    try {
      const chVideos = await getAllChannelVideos(ch.id);
      const name = ch.name || ch.channel_handle || 'channel';
      if (fmt === 'obsidian') {
        downloadFile(channelToObsidianMd(ch, chVideos, { timed: true }), `${sanitizeFilename(name)}_obsidian.md`);
        return;
      }
      const options = { timed };
      const content = fmt === 'md' ? channelToMd(name, chVideos, options) : channelToTxt(name, chVideos, options);
      downloadFile(content, `${sanitizeFilename(name)}${timed ? '_timed' : ''}.${fmt}`);
    } catch (e) {
      showMsg(t('msg.errExport', { error: (e as Error).message }), true);
    }
  }

  async function handleExportAll(fmt: 'txt' | 'md' | 'obsidian', timed = false) {
    try {
      const groups = await Promise.all(
        channels.map(async ch => ({
          channel: ch,
          videos: await getAllChannelVideos(ch.id),
        }))
      );
      if (fmt === 'obsidian') {
        const content = allChannelsToObsidianMd(groups, { timed: true });
        downloadFile(content, 'youtube_tudasbazis_obsidian.md');
        return;
      }
      const options = { timed };
      const content = fmt === 'md' ? allChannelsToMd(groups, options) : allChannelsToTxt(groups, options);
      downloadFile(content, `osszes_transkript${timed ? '_timed' : ''}.${fmt}`);
    } catch (e) {
      showMsg(t('msg.errExport', { error: (e as Error).message }), true);
    }
  }

  return (
    <>
      <div className="card">
        <h3 style={{ fontSize: '0.85rem', marginBottom: '0.5rem', color: '#aaa' }}>{t('header.addChannel')}</h3>
        <form onSubmit={handleChannelSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
          <textarea
            rows={3}
            placeholder={t('placeholder.channelUrls')}
            value={channelInput}
            onChange={e => setChannelInput(e.target.value)}
            style={{ resize: 'vertical' }}
          />
          <div style={{ display: 'flex', gap: '0.4rem' }}>
            <button type="submit" className="primary" disabled={busy || !channelInput.trim()} style={{ flex: 1 }}>
              {t('btn.add')}
            </button>
            <button type="button" onClick={() => fileInputRef.current?.click()} disabled={busy}>
              {t('btn.file')}
            </button>
          </div>
        </form>
        <input ref={fileInputRef} type="file" accept=".txt,.csv" style={{ display: 'none' }} onChange={handleFileUpload} />
      </div>

      <div className="card">
        <h3 style={{ fontSize: '0.85rem', marginBottom: '0.5rem', color: '#aaa' }}>{t('header.addVideo')}</h3>
        <form onSubmit={handleVideoSubmit} style={{ display: 'flex', gap: '0.4rem' }}>
          <input
            placeholder={t('placeholder.videoUrl')}
            value={videoInput}
            onChange={e => setVideoInput(e.target.value)}
          />
          <button type="submit" disabled={busy || !videoInput.trim()} style={{ whiteSpace: 'nowrap' }}>
            {t('btn.add')}
          </button>
        </form>
      </div>

      {msg && (
        <div style={{
          padding: '0.5rem 0.75rem',
          borderRadius: '6px',
          marginBottom: '0.5rem',
          background: msg.isError ? 'rgba(244,67,54,0.2)' : 'rgba(76,175,80,0.2)',
          color: msg.isError ? '#f88' : '#6fcf73',
          fontSize: '0.82rem',
        }}>
          {msg.text}
        </div>
      )}

      <div className="card">
        <h3 style={{ fontSize: '0.85rem', marginBottom: '0.5rem', color: '#aaa' }}>{t('header.allExport')}</h3>
        <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
          <button onClick={() => handleExportAll('txt')} style={{ flex: 1 }}>{t('export.txt')}</button>
          <button onClick={() => handleExportAll('md')} style={{ flex: 1 }}>{t('export.md')}</button>
          <button onClick={() => handleExportAll('txt', true)} style={{ flex: 1 }}>{t('export.txtTimed')}</button>
          <button onClick={() => handleExportAll('md', true)} style={{ flex: 1 }}>{t('export.mdTimed')}</button>
          <button onClick={() => handleExportAll('obsidian')} style={{ flex: 1 }}>{t('export.obsidian')}</button>
        </div>
      </div>

      <div style={{ marginBottom: '0.5rem' }}>
        <div
          onClick={() => onSelect(null)}
          style={{
            padding: '0.5rem 0.6rem',
            borderRadius: '6px',
            cursor: 'pointer',
            background: !selectedChannel ? 'var(--primary-dim)' : 'transparent',
            border: !selectedChannel ? '1px solid var(--primary)' : '1px solid transparent',
            marginBottom: '0.25rem',
            fontSize: '0.85rem',
          }}
        >
          {t('filter.all')} ({channels.length})
        </div>

        {channels.map(ch => (
          <div
            key={ch.id}
            style={{
              padding: '0.5rem 0.6rem',
              borderRadius: '6px',
              cursor: 'pointer',
              background: selectedChannel?.id === ch.id ? 'var(--primary-dim)' : 'var(--bg2)',
              border: selectedChannel?.id === ch.id ? '1px solid var(--primary)' : '1px solid var(--border)',
              marginBottom: '0.25rem',
            }}
            onClick={() => onSelect(ch)}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <div style={{ fontWeight: 600, fontSize: '0.85rem', marginBottom: '0.15rem' }}>
                  {ch.name || ch.channel_handle || t('state.unknownChannel')}
                </div>
                <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
                  <span className={`badge badge-${ch.status}`}>{(ch.status && STATUS_LABEL[ch.status]) || ch.status}</span>
                  {(ch.video_count ?? 0) > 0 && (
                    <span style={{ fontSize: '0.75rem', color: '#888' }}>{t('label.videoCount', { count: ch.video_count })}</span>
                  )}
                </div>
              </div>
            </div>
            {selectedChannel?.id === ch.id && (
              <div style={{ display: 'flex', gap: '0.3rem', marginTop: '0.5rem', flexWrap: 'wrap' }}>
                <button
                  onClick={e => { e.stopPropagation(); handleRefresh(ch); }}
                  style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem' }}
                >
                  {t('btn.refresh')}
                </button>
                <button
                  onClick={e => { e.stopPropagation(); handleExportChannel(ch, 'txt'); }}
                  style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem' }}
                >
                  {t('export.txt')}
                </button>
                <button
                  onClick={e => { e.stopPropagation(); handleExportChannel(ch, 'md'); }}
                  style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem' }}
                >
                  {t('export.md')}
                </button>
                <button
                  onClick={e => { e.stopPropagation(); handleExportChannel(ch, 'obsidian'); }}
                  style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem' }}
                >
                  {t('export.obsidian')}
                </button>
                <button
                  onClick={e => { e.stopPropagation(); handleExportChannel(ch, 'txt', true); }}
                  style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem' }}
                >
                  {t('export.txtTimed')}
                </button>
                <button
                  className="danger"
                  onClick={e => { e.stopPropagation(); handleDelete(ch); }}
                  style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem', marginLeft: 'auto' }}
                >
                  {t('btn.delete')}
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    </>
  );
}
