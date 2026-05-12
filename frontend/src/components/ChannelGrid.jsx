import { useState, useMemo } from 'react';
import { deleteChannel, getAllChannelVideos } from '../lib/directus.js';
import { generateAiNotesForChannel, refreshChannel } from '../lib/fetcher.js';
import {
  channelToTxt, channelToMd, channelToObsidianMd,
  downloadFile, sanitizeFilename,
} from '../lib/export.js';
import { useT } from '../lib/i18n.jsx';
import { useMessage } from '../lib/useMessage.js';

export default function ChannelGrid({ channels, totalVideos, selectedChannel, onSelect, onChannelsChanged }) {
  const { t } = useT();
  const { msg, showMsg } = useMessage();
  const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState('');
  const [sortKey, setSortKey] = useState('name_asc');
  const [topicFilter, setTopicFilter] = useState('all');

  const SORT_OPTIONS = [
    { value: 'name_asc',   label: t('sort.nameAZ') },
    { value: 'name_desc',  label: t('sort.nameZA') },
    { value: 'count_desc', label: t('sort.mostVideos') },
    { value: 'count_asc',  label: t('sort.fewestVideos') },
  ];

  const STATUS_LABEL = {
    pending: t('status.pending'),
    processing: t('status.inProgress'),
    done: t('status.done'),
    error: t('status.error'),
  };

  const topicOptions = useMemo(() => {
    const topics = [...new Set(
      channels
        .map(ch => (ch.topic || '').trim())
        .filter(Boolean)
    )];
    return topics.sort((a, b) => a.localeCompare(b));
  }, [channels]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    let list = channels.filter(ch => {
      const topic = (ch.topic || '').trim();
      if (topicFilter !== 'all' && topic !== topicFilter) return false;
      if (!q) return true;
      return `${ch.name || ''} ${ch.channel_handle || ''} ${topic}`
        .toLowerCase()
        .includes(q);
    });

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
  }, [channels, search, sortKey, topicFilter]);

  const groupedChannels = useMemo(() => {
    const groups = new Map();
    filtered.forEach(ch => {
      const topic = (ch.topic || '').trim() || t('label.noTopic');
      if (!groups.has(topic)) groups.set(topic, []);
      groups.get(topic).push(ch);
    });
    return [...groups.entries()].sort(([a], [b]) => {
      if (a === t('label.noTopic')) return 1;
      if (b === t('label.noTopic')) return -1;
      return a.localeCompare(b);
    });
  }, [filtered, t]);

  async function handleRefresh(e, ch) {
    e.stopPropagation();
    setBusy(true);
    try {
      await refreshChannel(ch.id);
      showMsg(t('msg.refreshQueued'));
    } catch (err) {
      showMsg(t('msg.errGeneric', { error: err.message }), true);
    } finally {
      setBusy(false);
    }
  }

  async function handleGenerateChannelAi(e, ch) {
    e.stopPropagation();
    setBusy(true);
    try {
      const result = await generateAiNotesForChannel(ch.id);
      showMsg(t('msg.aiQueued', { count: result.count }));
    } catch (err) {
      showMsg(t('msg.errAi', { error: err.message }), true);
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(e, ch) {
    e.stopPropagation();
    if (!confirm(t('confirm.deleteChannel', { name: ch.name || ch.channel_handle }))) return;
    await deleteChannel(ch.id);
    if (selectedChannel?.id === ch.id) onSelect(null);
    onChannelsChanged();
  }

  async function handleExport(e, ch, fmt) {
    e.stopPropagation();
    try {
      const chVideos = await getAllChannelVideos(ch.id);
      const name = ch.name || ch.channel_handle || 'channel';
      if (fmt === 'obsidian') {
        downloadFile(channelToObsidianMd(ch, chVideos, { timed: true }), `${sanitizeFilename(name)}_obsidian.md`);
        return;
      }
      const content = fmt === 'md' ? channelToMd(name, chVideos) : channelToTxt(name, chVideos);
      downloadFile(content, `${sanitizeFilename(name)}.${fmt}`);
    } catch (err) {
      showMsg(t('msg.errExport', { error: err.message }), true);
    }
  }

  const displayedTotalVideos = totalVideos ?? channels.reduce((sum, ch) => sum + (ch.video_count || 0), 0);

  return (
    <div className="channel-section">
      <div className="channel-section-header">
        <h3 style={{ fontSize: '0.9rem', color: 'var(--text2)', whiteSpace: 'nowrap' }}>
          {t('header.channels', { filtered: filtered.length, total: channels.length })}
        </h3>
        <input
          className="channel-search"
          placeholder={t('placeholder.searchChannel')}
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
        <select
          className="channel-topic-filter"
          value={topicFilter}
          onChange={e => setTopicFilter(e.target.value)}
        >
          <option value="all">{t('filter.allTopics')}</option>
          {topicOptions.map(topic => (
            <option key={topic} value={topic}>{topic}</option>
          ))}
        </select>
      </div>

      {msg && (
        <div className={`status-msg ${msg.isError ? 'status-error' : 'status-success'}`}>
          {msg.text}
        </div>
      )}

      <div className="channel-grid">
        <div
          className={`channel-card ${!selectedChannel ? 'channel-card-selected' : ''}`}
          onClick={() => onSelect(null)}
        >
          <div className="channel-card-name">{t('filter.all')}</div>
          <div className="channel-card-meta">
            <span style={{ fontSize: '0.75rem', color: 'var(--text2)' }}>
              {t('label.videoCount', { count: displayedTotalVideos })}
            </span>
          </div>
        </div>
      </div>

      {groupedChannels.map(([topic, topicChannels]) => (
        <section key={topic} className="channel-topic-group">
          <div className="channel-topic-header">
            <h4>{topic}</h4>
            <span>{t('label.channelCount', { count: topicChannels.length })}</span>
          </div>
          <div className="channel-grid">
            {topicChannels.map(ch => {
              const isSelected = selectedChannel?.id === ch.id;
              return (
                <div
                  key={ch.id}
                  className={`channel-card ${isSelected ? 'channel-card-selected' : ''}`}
                  onClick={() => onSelect(ch)}
                >
                  <div className="channel-card-name">
                    {ch.name || ch.channel_handle || t('state.unknownChannel')}
                  </div>
                  <div className="channel-card-meta">
                    <span className={`badge badge-${ch.status}`}>{STATUS_LABEL[ch.status] || ch.status}</span>
                    {ch.video_count > 0 && (
                      <span style={{ fontSize: '0.72rem', color: 'var(--text2)' }}>{t('label.videoCount', { count: ch.video_count })}</span>
                    )}
                  </div>
                  {isSelected && (
                    <div className="channel-card-actions">
                      <button onClick={e => handleRefresh(e, ch)} disabled={busy}>{t('btn.refresh')}</button>
                      <button onClick={e => handleGenerateChannelAi(e, ch)} disabled={busy}>{t('header.aiNotes')}</button>
                      <button onClick={e => handleExport(e, ch, 'txt')}>{t('export.txt')}</button>
                      <button onClick={e => handleExport(e, ch, 'md')}>{t('export.md')}</button>
                      <button onClick={e => handleExport(e, ch, 'obsidian')}>{t('export.obsidian')}</button>
                      <button className="danger" onClick={e => handleDelete(e, ch)}>{t('btn.delete')}</button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      ))}

      {filtered.length === 0 && (search || topicFilter !== 'all') && (
        <div style={{ fontSize: '0.85rem', color: 'var(--text2)', padding: '0.5rem' }}>
          {t('state.noChannelSearch', { query: search || topicFilter })}
        </div>
      )}
    </div>
  );
}
