import { useState, useMemo } from 'react';
import { deleteChannel, getAllChannelVideos } from '../lib/directus.js';
import { refreshChannel } from '../lib/fetcher.js';
import {
  channelToTxt, channelToMd,
  downloadFile, sanitizeFilename,
} from '../lib/export.js';

const SORT_OPTIONS = [
  { value: 'name_asc',   label: 'Név A–Z' },
  { value: 'name_desc',  label: 'Név Z–A' },
  { value: 'count_desc', label: 'Legtöbb videó' },
  { value: 'count_asc',  label: 'Legkevesebb videó' },
];

export default function ChannelGrid({ channels, selectedChannel, onSelect, onChannelsChanged }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [search, setSearch] = useState('');
  const [sortKey, setSortKey] = useState('name_asc');

  function showMsg(text, isError = false) {
    setMsg({ text, isError });
    setTimeout(() => setMsg(null), 4000);
  }

  const statusLabel = (s) => {
    const map = { pending: 'Várakozik', processing: 'Folyamatban', done: 'Kész', error: 'Hiba' };
    return map[s] || s;
  };

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    let list = q
      ? channels.filter(ch =>
          (ch.name || ch.channel_handle || '').toLowerCase().includes(q)
        )
      : [...channels];

    list.sort((a, b) => {
      const nameA = (a.name || a.channel_handle || '').toLowerCase();
      const nameB = (b.name || b.channel_handle || '').toLowerCase();
      if (sortKey === 'name_asc')   return nameA.localeCompare(nameB);
      if (sortKey === 'name_desc')  return nameB.localeCompare(nameA);
      if (sortKey === 'count_desc') return (b.video_count || 0) - (a.video_count || 0);
      if (sortKey === 'count_asc')  return (a.video_count || 0) - (b.video_count || 0);
      return 0;
    });
    return list;
  }, [channels, search, sortKey]);

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

  const totalVideos = channels.reduce((sum, ch) => sum + (ch.video_count || 0), 0);

  return (
    <div className="channel-section">
      <div className="channel-section-header">
        <h3 style={{ fontSize: '0.9rem', color: 'var(--text2)', whiteSpace: 'nowrap' }}>
          Csatornák ({filtered.length}/{channels.length})
        </h3>
        <input
          className="channel-search"
          placeholder="Keresés..."
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
        <select
          className="channel-sort"
          value={sortKey}
          onChange={e => setSortKey(e.target.value)}
        >
          {SORT_OPTIONS.map(o => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
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
              {totalVideos} videó
            </span>
          </div>
        </div>

        {filtered.map(ch => {
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

        {filtered.length === 0 && search && (
          <div style={{ fontSize: '0.85rem', color: 'var(--text2)', padding: '0.5rem' }}>
            Nincs találat: „{search}"
          </div>
        )}
      </div>
    </div>
  );
}
