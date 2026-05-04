import { useState, useRef } from 'react';
import { deleteChannel, getAllChannelVideos } from '../lib/directus.js';
import { fetchChannels, fetchVideo, refreshChannel } from '../lib/fetcher.js';
import {
  channelToTxt, channelToMd, channelToObsidianMd, allChannelsToTxt, allChannelsToMd, allChannelsToObsidianMd,
  downloadFile, sanitizeFilename,
} from '../lib/export.js';

function parseChannelFile(text) {
  const lines = text.split(/\r?\n/).map(l => l.trim()).filter(l => l && !l.startsWith('#'));
  // CSV: take first non-empty column that looks like a URL or handle
  return lines.map(line => {
    if (line.includes(',')) {
      const parts = line.split(',').map(p => p.trim().replace(/^["']|["']$/g, ''));
      return parts.find(p => p.includes('youtube') || p.startsWith('@') || p.startsWith('UC')) || parts[0];
    }
    return line;
  }).filter(Boolean);
}

export default function ChannelSidebar({ channels, selectedChannel, onSelect, onChannelsChanged, videos }) {
  const [channelInput, setChannelInput] = useState('');
  const [videoInput, setVideoInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const fileInputRef = useRef();

  function showMsg(text, isError = false) {
    setMsg({ text, isError });
    setTimeout(() => setMsg(null), 4000);
  }

  async function addChannels(urls) {
    if (!urls.length) return;
    setBusy(true);
    try {
      const result = await fetchChannels(urls);
      showMsg(`${result.count} csatorna sorba állítva`);
      onChannelsChanged();
    } catch (e) {
      showMsg('Hiba: ' + e.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function handleChannelSubmit(e) {
    e.preventDefault();
    const urls = channelInput.split('\n').map(l => l.trim()).filter(Boolean);
    await addChannels(urls);
    setChannelInput('');
  }

  async function handleVideoSubmit(e) {
    e.preventDefault();
    const url = videoInput.trim();
    if (!url) return;
    setBusy(true);
    try {
      await fetchVideo(url, selectedChannel?.id ?? null);
      showMsg('Videó sorba állítva');
      setVideoInput('');
    } catch (e) {
      showMsg('Hiba: ' + e.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function handleFileUpload(e) {
    const file = e.target.files[0];
    if (!file) return;
    const text = await file.text();
    const urls = parseChannelFile(text);
    e.target.value = '';
    await addChannels(urls);
  }

  async function handleDelete(ch) {
    if (!confirm(`Töröljük: ${ch.name || ch.channel_handle}?`)) return;
    await deleteChannel(ch.id);
    if (selectedChannel?.id === ch.id) onSelect(null);
    onChannelsChanged();
  }

  async function handleRefresh(ch) {
    setBusy(true);
    try {
      await refreshChannel(ch.id);
      showMsg('Frissítés sorba állítva');
    } catch (e) {
      showMsg('Hiba: ' + e.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function handleExportChannel(ch, fmt, timed = false) {
    try {
      const chVideos = await getAllChannelVideos(ch.id);
      const name = ch.name || ch.channel_handle || 'channel';
      if (fmt === 'obsidian') {
        downloadFile(channelToObsidianMd(ch, chVideos, { timed: true }), `${sanitizeFilename(name)}_obsidian.md`);
        return;
      }
      const options = { timed };
      const content = fmt === 'md' ? channelToMd(name, chVideos, options) : channelToTxt(name, chVideos, options);
      downloadFile(content, `${sanitizeFilename(name)}${timed ? '_idovel' : ''}.${fmt}`);
    } catch (e) {
      showMsg('Export hiba: ' + e.message, true);
    }
  }

  async function handleExportAll(fmt, timed = false) {
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
      downloadFile(content, `osszes_transkript${timed ? '_idovel' : ''}.${fmt}`);
    } catch (e) {
      showMsg('Export hiba: ' + e.message, true);
    }
  }

  const statusLabel = (s) => {
    const map = { pending: 'Várakozik', processing: 'Folyamatban', done: 'Kész', error: 'Hiba' };
    return map[s] || s;
  };

  return (
    <>
      {/* Add channel form */}
      <div className="card">
        <h3 style={{ fontSize: '0.85rem', marginBottom: '0.5rem', color: '#aaa' }}>Csatorna hozzáadása</h3>
        <form onSubmit={handleChannelSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
          <textarea
            rows={3}
            placeholder="URL-ek soronként (@handle, youtube.com/...)"
            value={channelInput}
            onChange={e => setChannelInput(e.target.value)}
            style={{ resize: 'vertical' }}
          />
          <div style={{ display: 'flex', gap: '0.4rem' }}>
            <button type="submit" className="primary" disabled={busy || !channelInput.trim()} style={{ flex: 1 }}>
              Hozzáad
            </button>
            <button type="button" onClick={() => fileInputRef.current.click()} disabled={busy}
              title="Fájl feltöltés (txt/csv)">
              Fájl
            </button>
          </div>
        </form>
        <input ref={fileInputRef} type="file" accept=".txt,.csv" style={{ display: 'none' }} onChange={handleFileUpload} />
      </div>

      {/* Add single video form */}
      <div className="card">
        <h3 style={{ fontSize: '0.85rem', marginBottom: '0.5rem', color: '#aaa' }}>Videó hozzáadása</h3>
        <form onSubmit={handleVideoSubmit} style={{ display: 'flex', gap: '0.4rem' }}>
          <input
            placeholder="youtube.com/watch?v=..."
            value={videoInput}
            onChange={e => setVideoInput(e.target.value)}
          />
          <button type="submit" disabled={busy || !videoInput.trim()} style={{ whiteSpace: 'nowrap' }}>
            Hozzáad
          </button>
        </form>
      </div>

      {/* Status message */}
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

      {/* Export all */}
      <div className="card">
        <h3 style={{ fontSize: '0.85rem', marginBottom: '0.5rem', color: '#aaa' }}>Összes export</h3>
        <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
          <button onClick={() => handleExportAll('txt')} style={{ flex: 1 }}>TXT</button>
          <button onClick={() => handleExportAll('md')} style={{ flex: 1 }}>MD</button>
          <button onClick={() => handleExportAll('txt', true)} style={{ flex: 1 }}>TXT idővel</button>
          <button onClick={() => handleExportAll('md', true)} style={{ flex: 1 }}>MD idővel</button>
          <button onClick={() => handleExportAll('obsidian')} style={{ flex: 1 }}>Obsidian</button>
        </div>
      </div>

      {/* Channel list */}
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
          Összes csatorna ({channels.length})
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
                  {ch.name || ch.channel_handle || 'Ismeretlen'}
                </div>
                <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
                  <span className={`badge badge-${ch.status}`}>{statusLabel(ch.status)}</span>
                  {ch.video_count > 0 && (
                    <span style={{ fontSize: '0.75rem', color: '#888' }}>{ch.video_count} videó</span>
                  )}
                </div>
              </div>
            </div>
            {selectedChannel?.id === ch.id && (
              <div style={{ display: 'flex', gap: '0.3rem', marginTop: '0.5rem', flexWrap: 'wrap' }}>
                <button
                  onClick={e => { e.stopPropagation(); handleRefresh(ch); }}
                  title="Frissítés" style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem' }}
                >
                  Frissít
                </button>
                <button
                  onClick={e => { e.stopPropagation(); handleExportChannel(ch, 'txt'); }}
                  style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem' }}
                >
                  TXT
                </button>
                <button
                  onClick={e => { e.stopPropagation(); handleExportChannel(ch, 'md'); }}
                  style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem' }}
                >
                  MD
                </button>
                <button
                  onClick={e => { e.stopPropagation(); handleExportChannel(ch, 'obsidian'); }}
                  style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem' }}
                >
                  Obsidian
                </button>
                <button
                  onClick={e => { e.stopPropagation(); handleExportChannel(ch, 'txt', true); }}
                  style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem' }}
                >
                  TXT idővel
                </button>
                <button
                  className="danger"
                  onClick={e => { e.stopPropagation(); handleDelete(ch); }}
                  style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem', marginLeft: 'auto' }}
                >
                  Töröl
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    </>
  );
}
