import { useState, useRef, type FormEvent, type ChangeEvent } from 'react';
import { fetchChannels, fetchVideo, refreshDates, generateAiNotes } from '../lib/fetcher.ts';
import { getAllChannelVideos } from '../lib/directus.ts';
import {
  channelToTxt, channelToMd, allChannelsToTxt, allChannelsToMd, allChannelsToObsidianMd,
  downloadFile, sanitizeFilename,
} from '../lib/export.ts';
import { useT } from '../lib/i18n.tsx';
import { parseChannelFile } from '../lib/channelUtils.ts';
import { useMessage } from '../lib/useMessage.ts';
import type { Channel } from '../types.ts';

interface TopActionsProps {
  channels: Channel[];
  selectedChannel: Channel | null;
  onChannelsChanged: () => void;
}

export default function TopActions({ channels, selectedChannel, onChannelsChanged }: TopActionsProps) {
  const { t } = useT();
  const { msg, showMsg } = useMessage();
  const [channelInput, setChannelInput] = useState('');
  const [videoInput, setVideoInput] = useState('');
  const [busy, setBusy] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

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

  async function handleExportAll(fmt: 'txt' | 'md' | 'obsidian', timed = false) {
    try {
      const groups = await Promise.all(
        channels.map(async ch => ({
          channel: ch,
          videos: await getAllChannelVideos(ch.id),
        }))
      );
      const options = { timed };
      if (fmt === 'obsidian') {
        const content = allChannelsToObsidianMd(groups, { timed: true });
        downloadFile(content, 'youtube_tudasbazis_obsidian.md');
        return;
      }
      const content = fmt === 'md' ? allChannelsToMd(groups, options) : allChannelsToTxt(groups, options);
      downloadFile(content, `osszes_transkript${timed ? '_idovel' : ''}.${fmt}`);
    } catch (e) {
      showMsg(t('msg.errExport', { error: (e as Error).message }), true);
    }
  }

  return (
    <div className="top-actions">
      <div className="card top-action-card">
        <h3 className="card-title">{t('header.addChannel')}</h3>
        <form onSubmit={handleChannelSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
          <textarea
            rows={2}
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

      <div className="card top-action-card">
        <h3 className="card-title">{t('header.addVideo')}</h3>
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

      <div className="card top-action-card">
        <h3 className="card-title">{t('header.allExport')}</h3>
        <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
          <button onClick={() => handleExportAll('txt')} style={{ flex: 1 }}>{t('export.txt')}</button>
          <button onClick={() => handleExportAll('md')} style={{ flex: 1 }}>{t('export.md')}</button>
          <button onClick={() => handleExportAll('txt', true)} style={{ flex: 1 }}>{t('export.txtTimed')}</button>
          <button onClick={() => handleExportAll('md', true)} style={{ flex: 1 }}>{t('export.mdTimed')}</button>
          <button onClick={() => handleExportAll('obsidian')} style={{ flex: 1 }}>{t('export.obsidian')}</button>
        </div>
      </div>

      <div className="card top-action-card">
        <h3 className="card-title">{t('header.missingDates')}</h3>
        <button
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await refreshDates();
              showMsg(t('msg.dateRefreshQueued'));
            } catch (e) {
              showMsg(t('msg.errGeneric', { error: (e as Error).message }), true);
            } finally {
              setBusy(false);
            }
          }}
        >
          {t('btn.refresh')}
        </button>
      </div>

      <div className="card top-action-card">
        <h3 className="card-title">{t('header.aiNotes')}</h3>
        <button
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              const result = await generateAiNotes();
              showMsg(!result.queued
                ? t('msg.aiBatchRunning', { jobId: result.job_id.slice(0, 8) })
                : t('msg.aiBatchQueued', { limit: result.limit })
              );
            } catch (e) {
              showMsg(t('msg.errAi', { error: (e as Error).message }), true);
            } finally {
              setBusy(false);
            }
          }}
        >
          {t('btn.generateMissing')}
        </button>
      </div>

      {msg && (
        <div className={`status-msg ${msg.isError ? 'status-error' : 'status-success'}`}>
          {msg.text}
        </div>
      )}
    </div>
  );
}
