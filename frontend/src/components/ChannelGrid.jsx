import { useState } from 'react';
import { deleteChannel, getAllChannelVideos } from '../lib/directus.js';
import { refreshChannel } from '../lib/fetcher.js';
import {
  channelToTxt, channelToMd,
  downloadFile, sanitizeFilename,
} from '../lib/export.js';

export default function ChannelGrid({ channels, selectedChannel, onSelect, onChannelsChanged }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  function showMsg(text, isError = false) {
    setMsg({ text, isError });
    setTimeout(() => setMsg(null), 4000);
  }

  const statusLabel = (s) => {
    const map = { pending: 'Várakozik', processing: 'Folyamatban', done: 'Kész', error: 'Hiba' };
    return map[s] || s;
  };

  async function handleRefresh(e, ch) {
    e.stopPropagation();
    setBusy(true);
    try {
      await refreshChannel(ch.id);
      showMsg('Frissítés sorba állítva');
    } catch (err) {
      showMsg('Hiba: ' + err.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(e, ch) {
    e.stopPropagation();
    if (!confirm(`Töröljük: ${ch.name || ch.channel_handle}?`)) return;
    await deleteChannel(ch.id);
    if (selectedChannel?.id === ch.id) onSelect(null);
    onChannelsChanged();
  }

  async function handleExport(e, ch, fmt) {
    e.stopPropagation();
    try {
      const chVideos = await getAllChannelVideos(ch.id);
      const name = ch.name || ch.channel_handle || 'channel';
      const content = fmt === 'md' ? channelToMd(name, chVideos) : channelToTxt(name, chVideos);
      downloadFile(content, `${sanitizeFilename(name)}.${fmt}`);
    } catch (err) {
      showMsg('Export hiba: ' + err.message, true);
    }
  }

  return (
    <div className="channel-section">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
        <h3 style={{ fontSize: '0.9rem', color: 'var(--text2)' }}>Összes csatorna ({channels.length})</h3>
      </div>

      {msg && (
        <div className={`status-msg ${msg.isError ? 'status-error' : 'status-success'}`}>
          {msg.text}
        </div>
      )}

      <div className="channel-grid">
        {/* All channels option */}
        <div
          className={`channel-card ${!selectedChannel ? 'channel-card-selected' : ''}`}
          onClick={() => onSelect(null)}
        >
          <div className="channel-card-name">Összes</div>
          <div className="channel-card-meta">
            <span style={{ fontSize: '0.75rem', color: 'var(--text2)' }}>
              {channels.reduce((sum, ch) => sum + (ch.video_count || 0), 0)} videó
            </span>
          </div>
        </div>

        {channels.map(ch => {
          const isSelected = selectedChannel?.id === ch.id;
          return (
            <div
              key={ch.id}
              className={`channel-card ${isSelected ? 'channel-card-selected' : ''}`}
              onClick={() => onSelect(ch)}
            >
              <div className="channel-card-name">
                {ch.name || ch.channel_handle || 'Ismeretlen'}
              </div>
              <div className="channel-card-meta">
                <span className={`badge badge-${ch.status}`}>{statusLabel(ch.status)}</span>
                {ch.video_count > 0 && (
                  <span style={{ fontSize: '0.72rem', color: 'var(--text2)' }}>{ch.video_count} videó</span>
                )}
              </div>
              {isSelected && (
                <div className="channel-card-actions">
                  <button onClick={e => handleRefresh(e, ch)} disabled={busy}>Frissít</button>
                  <button onClick={e => handleExport(e, ch, 'txt')}>TXT</button>
                  <button onClick={e => handleExport(e, ch, 'md')}>MD</button>
                  <button className="danger" onClick={e => handleDelete(e, ch)}>Töröl</button>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
