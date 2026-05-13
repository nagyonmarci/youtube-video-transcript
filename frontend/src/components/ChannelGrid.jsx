import { useState, useMemo, useRef, useCallback } from 'react';
import { deleteChannel, getAllChannelVideos, updateChannel } from '../lib/directus.js';
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

  // Drag & drop state
  const [draggedChannelId, setDraggedChannelId] = useState(null);
  const [dragOverTopic, setDragOverTopic] = useState(null);

  // Inline topic rename state: { oldName, value }
  const [editingTopic, setEditingTopic] = useState(null);
  const topicInputRef = useRef(null);

  // New topic creation
  const [pendingTopics, setPendingTopics] = useState([]);
  const [addingTopic, setAddingTopic] = useState(false);
  const [newTopicValue, setNewTopicValue] = useState('');
  const newTopicInputRef = useRef(null);

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

  const noTopicLabel = t('label.noTopic');

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
      const topic = (ch.topic || '').trim() || noTopicLabel;
      if (!groups.has(topic)) groups.set(topic, []);
      groups.get(topic).push(ch);
    });
    return [...groups.entries()].sort(([a], [b]) => {
      if (a === noTopicLabel) return 1;
      if (b === noTopicLabel) return -1;
      return a.localeCompare(b);
    });
  }, [filtered, noTopicLabel]);

  // Pending topics not already backed by real channels
  const pendingTopicsToShow = useMemo(() =>
    pendingTopics.filter(pt => !groupedChannels.some(([label]) => label === pt)),
    [pendingTopics, groupedChannels]
  );

  const hasNoTopicGroup = groupedChannels.some(([label]) => label === noTopicLabel);

  // ---- Channel action handlers ----

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

  // ---- Drag & drop handlers ----

  const handleDragStart = useCallback((e, ch) => {
    setDraggedChannelId(ch.id);
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', ch.id);
  }, []);

  const handleDragEnd = useCallback(() => {
    setDraggedChannelId(null);
    setDragOverTopic(null);
  }, []);

  const handleDragOver = useCallback((e, topicLabel) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    setDragOverTopic(topicLabel);
  }, []);

  const handleDragLeave = useCallback((e) => {
    if (!e.currentTarget.contains(e.relatedTarget)) {
      setDragOverTopic(null);
    }
  }, []);

  const handleDrop = useCallback(async (e, targetLabel) => {
    e.preventDefault();
    const id = draggedChannelId;
    setDraggedChannelId(null);
    setDragOverTopic(null);
    if (!id) return;

    const draggedCh = channels.find(c => c.id === id);
    if (!draggedCh) return;

    const newTopic = targetLabel === noTopicLabel ? '' : targetLabel;
    const currentTopic = (draggedCh.topic || '').trim();
    if (currentTopic === newTopic) return;

    try {
      await updateChannel(id, { topic: newTopic });
      // If target was a pending (empty) topic, it's now backed by a real channel
      setPendingTopics(prev => prev.filter(p => p !== newTopic));
      onChannelsChanged();
    } catch (err) {
      showMsg(t('msg.errGeneric', { error: err.message }), true);
    }
  }, [draggedChannelId, channels, noTopicLabel, onChannelsChanged, showMsg, t]);

  // ---- Topic group rename ----

  function startEditTopic(e, topicLabel) {
    e.stopPropagation();
    setEditingTopic({ oldName: topicLabel, value: topicLabel === noTopicLabel ? '' : topicLabel });
    setTimeout(() => topicInputRef.current?.select(), 0);
  }

  async function commitTopicRename() {
    if (!editingTopic) return;
    const { oldName, value } = editingTopic;
    setEditingTopic(null);

    const newName = value.trim();
    const oldKey = oldName === noTopicLabel ? '' : oldName;
    if (newName === oldKey) return;

    // If it was a pending topic, just rename it locally
    if (pendingTopics.includes(oldName)) {
      if (newName && !pendingTopics.includes(newName) && !groupedChannels.some(([l]) => l === newName)) {
        setPendingTopics(prev => prev.map(p => p === oldName ? newName : p));
      } else {
        setPendingTopics(prev => prev.filter(p => p !== oldName));
      }
      return;
    }

    const toUpdate = channels.filter(ch => (ch.topic || '').trim() === oldKey);
    if (!toUpdate.length) return;
    try {
      await Promise.all(toUpdate.map(ch => updateChannel(ch.id, { topic: newName })));
      onChannelsChanged();
    } catch (err) {
      showMsg(t('msg.errGeneric', { error: err.message }), true);
    }
  }

  function handleTopicKeyDown(e) {
    if (e.key === 'Enter') { e.preventDefault(); commitTopicRename(); }
    if (e.key === 'Escape') setEditingTopic(null);
  }

  // ---- Topic delete ----

  async function handleDeleteTopic(e, topicLabel) {
    e.stopPropagation();

    // Pending topic has no channels — just discard it
    if (pendingTopics.includes(topicLabel)) {
      setPendingTopics(prev => prev.filter(p => p !== topicLabel));
      return;
    }

    const topicKey = topicLabel === noTopicLabel ? '' : topicLabel;
    const toUpdate = channels.filter(ch => (ch.topic || '').trim() === topicKey);
    if (toUpdate.length && !confirm(t('confirm.deleteTopic', { name: topicLabel, count: toUpdate.length }))) return;
    try {
      await Promise.all(toUpdate.map(ch => updateChannel(ch.id, { topic: '' })));
      onChannelsChanged();
    } catch (err) {
      showMsg(t('msg.errGeneric', { error: err.message }), true);
    }
  }

  // ---- New topic creation ----

  function handleAddTopic() {
    const name = newTopicValue.trim();
    setNewTopicValue('');
    setAddingTopic(false);
    if (!name) return;
    if (pendingTopics.includes(name) || groupedChannels.some(([l]) => l === name)) return;
    setPendingTopics(prev => [...prev, name]);
  }

  function handleNewTopicKeyDown(e) {
    if (e.key === 'Enter') { e.preventDefault(); handleAddTopic(); }
    if (e.key === 'Escape') { setAddingTopic(false); setNewTopicValue(''); }
  }

  // ---- Render ----

  const displayedTotalVideos = totalVideos ?? channels.reduce((sum, ch) => sum + (ch.video_count || 0), 0);

  function renderTopicSection(topicLabel, topicChannels, isPending = false) {
    const isEditing = editingTopic?.oldName === topicLabel;
    const isDropOver = dragOverTopic === topicLabel;
    const isDragging = draggedChannelId !== null;
    const canDelete = topicLabel !== noTopicLabel || isPending;

    return (
      <section
        key={topicLabel}
        className={`channel-topic-group${isDropOver ? ' channel-drop-over' : ''}${isPending ? ' channel-topic-pending' : ''}`}
        onDragOver={isDragging ? (e) => handleDragOver(e, topicLabel) : undefined}
        onDragLeave={isDragging ? handleDragLeave : undefined}
        onDrop={isDragging ? (e) => handleDrop(e, topicLabel) : undefined}
      >
        <div className="channel-topic-header">
          {isEditing ? (
            <input
              ref={topicInputRef}
              className="channel-topic-edit-input"
              value={editingTopic.value}
              onChange={e => setEditingTopic(et => ({ ...et, value: e.target.value }))}
              onBlur={commitTopicRename}
              onKeyDown={handleTopicKeyDown}
              onClick={e => e.stopPropagation()}
              placeholder={noTopicLabel}
            />
          ) : (
            <h4
              className={`channel-topic-label${topicLabel === noTopicLabel ? ' channel-topic-label-muted' : ''}`}
              onClick={topicLabel !== noTopicLabel ? (e) => startEditTopic(e, topicLabel) : undefined}
              title={topicLabel !== noTopicLabel ? t('label.clickToRename') : undefined}
            >
              {topicLabel}
            </h4>
          )}
          <span className="channel-topic-count">{t('label.channelCount', { count: topicChannels.length })}</span>
          {canDelete && (
            <button
              className="channel-topic-delete-btn"
              onClick={(e) => handleDeleteTopic(e, topicLabel)}
              title={t('btn.deleteTopic')}
              tabIndex={-1}
            >×</button>
          )}
        </div>
        <div className="channel-grid">
          {topicChannels.map(ch => {
            const isSelected = selectedChannel?.id === ch.id;
            const isDraggingThis = draggedChannelId === ch.id;
            return (
              <div
                key={ch.id}
                className={`channel-card${isSelected ? ' channel-card-selected' : ''}${isDraggingThis ? ' channel-card-dragging' : ''}`}
                draggable
                onDragStart={(e) => handleDragStart(e, ch)}
                onDragEnd={handleDragEnd}
                onClick={() => !draggedChannelId && onSelect(ch)}
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
          {topicChannels.length === 0 && (
            <div className="channel-drop-hint">{t('label.dropHere')}</div>
          )}
        </div>
      </section>
    );
  }

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

      {groupedChannels.map(([topic, topicChannels]) =>
        renderTopicSection(topic, topicChannels)
      )}

      {/* Pending (newly created, empty) topic groups */}
      {pendingTopicsToShow.map(pt => renderTopicSection(pt, [], true))}

      {/* "No topic" drop zone while dragging, if no ungrouped channels exist */}
      {draggedChannelId && !hasNoTopicGroup && topicFilter === 'all' && !search &&
        renderTopicSection(noTopicLabel, [])
      }

      {filtered.length === 0 && (search || topicFilter !== 'all') && (
        <div style={{ fontSize: '0.85rem', color: 'var(--text2)', padding: '0.5rem' }}>
          {t('state.noChannelSearch', { query: search || topicFilter })}
        </div>
      )}

      {/* Add new topic */}
      {topicFilter === 'all' && !search && (
        <div className="channel-add-topic">
          {addingTopic ? (
            <div className="channel-add-topic-form">
              <input
                ref={newTopicInputRef}
                className="channel-topic-edit-input"
                value={newTopicValue}
                onChange={e => setNewTopicValue(e.target.value)}
                onKeyDown={handleNewTopicKeyDown}
                placeholder={t('placeholder.newTopic')}
                autoFocus
              />
              <button onClick={handleAddTopic}>{t('btn.add')}</button>
              <button onClick={() => { setAddingTopic(false); setNewTopicValue(''); }}>{t('btn.cancel')}</button>
            </div>
          ) : (
            <button className="channel-add-topic-btn" onClick={() => setAddingTopic(true)}>
              + {t('btn.newTopic')}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
