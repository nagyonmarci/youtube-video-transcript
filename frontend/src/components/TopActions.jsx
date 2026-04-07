import { useState, useRef } from 'react';
import { fetchChannels, fetchVideo } from '../lib/fetcher.js';
import { getAllChannelVideos } from '../lib/directus.js';
import {
  channelToTxt, channelToMd, allChannelsToTxt, allChannelsToMd,
  downloadFile, sanitizeFilename,
} from '../lib/export.js';

function parseChannelFile(text) {
  const lines = text.split(/\r?\n/).map(l => l.trim()).filter(l => l && !l.startsWith('#'));
  return lines.map(line => {
    if (line.includes(',')) {
      const parts = line.split(',').map(p => p.trim().replace(/^["']|["']$/g, ''));
      return parts.find(p => p.includes('youtube') || p.startsWith('@') || p.startsWith('UC')) || parts[0];
    }
    return line;
  }).filter(Boolean);
}

export default function TopActions({ channels, selectedChannel, onChannelsChanged }) {
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

  async function handleExportAll(fmt) {
    try {
      const groups = await Promise.all(
        channels.map(async ch => ({
          channel: ch,
          videos: await getAllChannelVideos(ch.id),
        }))
      );
      const content = fmt === 'md' ? allChannelsToMd(groups) : allChannelsToTxt(groups);
      downloadFile(content, `osszes_transkript.${fmt}`);
    } catch (e) {
      showMsg('Export hiba: ' + e.message, true);
    }
  }

  return (
    <div className="top-actions">
      {/* Add channel */}
      <div className="card top-action-card">
        <h3 className="card-title">Csatorna hozzáadása</h3>
        <form onSubmit={handleChannelSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
          <textarea
            rows={2}
            placeholder="URL-ek soronként (@handle, youtube.com/...)"
            value={channelInput}
            onChange={e => setChannelInput(e.target.value)}
            style={{ resize: 'vertical' }}
          />
          <div style={{ display: 'flex', gap: '0.4rem' }}>
            <button type="submit" className="primary" disabled={busy || !channelInput.trim()} style={{ flex: 1 }}>
              Hozzáad
            </button>
            <button type="button" onClick={() => fileInputRef.current.click()} disabled={busy}>
              Fájl
            </button>
          </div>
        </form>
        <input ref={fileInputRef} type="file" accept=".txt,.csv" style={{ display: 'none' }} onChange={handleFileUpload} />
      </div>

      {/* Add video */}
      <div className="card top-action-card">
        <h3 className="card-title">Videó hozzáadása</h3>
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

      {/* Export all */}
      <div className="card top-action-card">
        <h3 className="card-title">Összes export</h3>
        <div style={{ display: 'flex', gap: '0.4rem' }}>
          <button onClick={() => handleExportAll('txt')} style={{ flex: 1 }}>TXT</button>
          <button onClick={() => handleExportAll('md')} style={{ flex: 1 }}>MD</button>
        </div>
      </div>

      {/* Status message */}
      {msg && (
        <div className={`status-msg ${msg.isError ? 'status-error' : 'status-success'}`}>
          {msg.text}
        </div>
      )}
    </div>
  );
}
