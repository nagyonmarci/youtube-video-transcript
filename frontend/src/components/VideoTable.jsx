import { useState, useEffect, useRef, useCallback } from 'react';
import { deleteAiNoteForVideo, generateAiNoteForVideo, generateQuickNoteForVideo } from '../lib/fetcher.js';
import { videoToTxt, videoToMd, videoToObsidianMd, obsidianFilename, videoToMarkmapMd, markmapFilename, downloadFile, sanitizeFilename, videosToCsv, videosToJson } from '../lib/export.js';
import { useT } from '../lib/i18n.jsx';
import { formatDuration, formatDate } from '../lib/formatUtils.js';
import { useMessage } from '../lib/useMessage.js';
import { TOAST_TIMEOUT_MS, SEARCH_DEBOUNCE_MS } from '../lib/constants.js';

async function bulkGenerateAiNotes(videos) {
  const errors = [];
  for (const v of videos) {
    try { await generateAiNoteForVideo(v.id); }
    catch { errors.push(v.title || v.video_id); }
  }
  return errors;
}

async function bulkDeleteAiNotes(videos) {
  const errors = [];
  for (const v of videos) {
    try { await deleteAiNoteForVideo(v.id); }
    catch { errors.push(v.title || v.video_id); }
  }
  return errors;
}

export default function VideoTable({
  videos,
  totalCount,
  hasMore = false,
  loadingMore = false,
  onLoadMore,
  search,
  onSearchChange,
  sort,
  onSortChange,
  statusFilter = 'all',
  onStatusFilterChange,
  aiFilter = 'all',
  onAiFilterChange,
  membersFilter = 'all',
  onMembersFilterChange,
  loading,
  onSelectVideo,
  onVideosChanged,
  selectedChannel,
  emptyMessage,
  searchPlaceholder,
}) {
  const { t } = useT();
  const searchInputRef = useRef();
  const [localSearch, setLocalSearch] = useState(search);
  const [aiBusyId, setAiBusyId] = useState(null);
  const [exportMenuId, setExportMenuId] = useState(null);
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const { msg: actionMsg, showMsg: showActionMsg } = useMessage(TOAST_TIMEOUT_MS);
  const debounceRef = useRef(null);
  const loadMoreRef = useRef(null);

  const STATUS_MAP = {
    done: { icon: '✅', label: t('status.done') },
    pending: { icon: '⏳', label: t('status.pending') },
    processing: { icon: '🔄', label: t('status.processing') },
    no_transcript: { icon: '—', label: t('status.none') },
    error: { icon: '⚠️', label: t('status.error') },
  };

  const AI_STATUS_MAP = {
    done: t('status.aiDone'),
    pending: t('status.aiRunning'),
    error: t('status.aiError'),
  };

  useEffect(() => { setSelectedIds(new Set()); }, [search, statusFilter, aiFilter, membersFilter, sort, selectedChannel?.id]);

  useEffect(() => () => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
  }, []);

  useEffect(() => {
    const target = loadMoreRef.current;
    if (!target || !hasMore || loading || loadingMore) return undefined;
    const observer = new IntersectionObserver(
      entries => {
        if (entries[0]?.isIntersecting) onLoadMore?.();
      },
      { root: null, rootMargin: '600px 0px', threshold: 0.01 }
    );
    observer.observe(target);
    return () => observer.disconnect();
  }, [hasMore, loading, loadingMore, onLoadMore, videos.length]);

  useEffect(() => {
    if (!exportMenuId) return;
    const handler = () => setExportMenuId(null);
    document.addEventListener('click', handler);
    return () => document.removeEventListener('click', handler);
  }, [exportMenuId]);

  const allSelected = videos.length > 0 && videos.every(v => selectedIds.has(v.id));
  const someSelected = selectedIds.size > 0;
  const selectedVideos = videos.filter(v => selectedIds.has(v.id));

  function toggleSelect(id) {
    setSelectedIds(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  function toggleSelectAll() {
    if (allSelected) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(videos.map(v => v.id)));
    }
  }

  async function handleBulkAiNotes() {
    if (!selectedVideos.length) return;
    setBulkBusy(true);
    try {
      const errors = await bulkGenerateAiNotes(selectedVideos.filter(v => v.transcript));
      await onVideosChanged?.();
      if (errors.length) {
        showActionMsg(t('msg.bulkAiErrors', { count: errors.length, titles: errors.slice(0, 3).join(', ') }), true);
      } else {
        showActionMsg(t('msg.aiQueued', { count: selectedVideos.filter(v => v.transcript).length }));
      }
    } finally {
      setBulkBusy(false);
    }
  }

  async function handleBulkDeleteAi() {
    if (!selectedVideos.length) return;
    if (!confirm(t('confirm.deleteAiNotes', { count: selectedVideos.length }))) return;
    setBulkBusy(true);
    try {
      const errors = await bulkDeleteAiNotes(selectedVideos);
      await onVideosChanged?.();
      if (errors.length) {
        showActionMsg(t('msg.bulkDeleteErrors', { count: errors.length, titles: errors.slice(0, 3).join(', ') }), true);
      } else {
        showActionMsg(t('msg.saved'));
      }
    } finally {
      setBulkBusy(false);
    }
  }

  function handleBulkExportMd() {
    const combined = selectedVideos.map(v => videoToMd(v)).join('\n\n---\n\n');
    downloadFile(combined, `bulk_export_${selectedVideos.length}.md`);
  }

  function handleBulkExportObsidian() {
    const combined = selectedVideos.map(v => videoToObsidianMd(v, { channel: selectedChannel, timed: true })).join('\n\n---\n\n');
    downloadFile(combined, `bulk_obsidian_${selectedVideos.length}.md`);
  }

  useEffect(() => {
    setLocalSearch(search);
  }, [search]);

  const handleSearchInput = useCallback((e) => {
    const value = e.target.value;
    setLocalSearch(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      onSearchChange(value);
    }, SEARCH_DEBOUNCE_MS);
  }, [onSearchChange]);

  const sortField = sort.startsWith('-') ? sort.slice(1) : sort;
  const sortDesc = sort.startsWith('-');

  function handleHeaderClick(field) {
    if (field === sortField) {
      onSortChange(sortDesc ? field : `-${field}`);
    } else {
      onSortChange(`-${field}`);
    }
  }

  function renderSortIcon(field) {
    if (field !== sortField) return null;
    return sortDesc ? ' ↓' : ' ↑';
  }

  async function handleGenerateQuickNote(e, video) {
    e.stopPropagation();
    setAiBusyId(video.id);
    try {
      await generateQuickNoteForVideo(video.id);
      showActionMsg(t('msg.aiQueued', { count: 1 }));
      await onVideosChanged?.();
    } catch (err) {
      showActionMsg(t('msg.errAi', { error: err.message }), true);
    } finally {
      setAiBusyId(null);
    }
  }

  async function handleGenerateAiNote(e, video) {
    e.stopPropagation();
    setAiBusyId(video.id);
    try {
      await generateAiNoteForVideo(video.id);
      showActionMsg(t('msg.aiQueued', { count: 1 }));
      await onVideosChanged?.();
    } catch (err) {
      showActionMsg(t('msg.errAi', { error: err.message }), true);
    } finally {
      setAiBusyId(null);
    }
  }

  async function handleDeleteAiNote(e, video) {
    e.stopPropagation();
    if (!confirm(t('confirm.deleteAiNote', { title: video.title || video.video_id }))) return;
    setAiBusyId(video.id);
    try {
      await deleteAiNoteForVideo(video.id);
      await onVideosChanged?.();
    } catch (err) {
      alert(t('msg.errAiDelete', { error: err.message }));
    } finally {
      setAiBusyId(null);
    }
  }

  return (
    <div className="video-section">
      <div className="video-header">
        <h2 className="video-title">
          {selectedChannel
            ? t('header.channelVideos', { name: selectedChannel.name || selectedChannel.channel_handle, count: totalCount })
            : t('header.allVideos', { count: totalCount })
          }
        </h2>
        <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center', flexWrap: 'wrap' }}>
          <input
            ref={searchInputRef}
            className="video-search"
            placeholder={searchPlaceholder ?? t('placeholder.searchVideo')}
            value={localSearch}
            onChange={handleSearchInput}
            style={{ width: '200px' }}
          />
          <select
            value={statusFilter}
            onChange={e => onStatusFilterChange?.(e.target.value)}
            style={{ width: 'auto' }}
          >
            <option value="all">{t('filter.allStatus')}</option>
            <option value="done">{t('filter.done')}</option>
            <option value="pending">{t('filter.pending')}</option>
            <option value="no_transcript">{t('filter.noTranscript')}</option>
            <option value="error">{t('filter.error')}</option>
          </select>
          <select
            value={aiFilter}
            onChange={e => onAiFilterChange?.(e.target.value)}
            style={{ width: 'auto' }}
          >
            <option value="all">{t('filter.allAi')}</option>
            <option value="done">{t('filter.aiDone')}</option>
            <option value="missing">{t('filter.aiMissing')}</option>
            <option value="error">{t('filter.aiError')}</option>
          </select>
          <select
            value={membersFilter}
            onChange={e => onMembersFilterChange?.(e.target.value)}
            style={{ width: 'auto' }}
          >
            <option value="all">{t('filter.membersAll')}</option>
            <option value="hide">{t('filter.membersHidden')}</option>
            <option value="only">{t('filter.membersOnly')}</option>
          </select>
        </div>
      </div>

      {actionMsg && (
        <div className={`status-msg ${actionMsg.isError ? 'status-error' : 'status-success'}`}>
          {actionMsg.text}
        </div>
      )}

      {loading ? (
        <div className="video-empty">{t('state.loading')}</div>
      ) : totalCount === 0 ? (
        <div className="video-empty">
          {emptyMessage ?? (search ? t('state.noResults') : t('state.noVideos'))}
        </div>
      ) : (
        <>
          {someSelected && (
            <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center', padding: '0.4rem 0.5rem', background: 'var(--primary-dim)', border: '1px solid var(--primary)', borderRadius: '6px', marginBottom: '0.4rem', flexWrap: 'wrap' }}>
              <span style={{ fontSize: '0.82rem', fontWeight: 600 }}>{t('label.selected', { count: selectedIds.size })}</span>
              <button className="btn-sm" disabled={bulkBusy} onClick={handleBulkAiNotes}>{t('btn.aiGenerate')}</button>
              <button className="btn-sm danger" disabled={bulkBusy} onClick={handleBulkDeleteAi}>{t('btn.aiDelete')}</button>
              <button className="btn-sm" disabled={bulkBusy} onClick={handleBulkExportMd}>{t('btn.mdDownload')}</button>
              <button className="btn-sm" disabled={bulkBusy} onClick={handleBulkExportObsidian}>{t('btn.obsidianDownload')}</button>
              <button className="btn-sm" onClick={() => downloadFile(videosToCsv(selectedVideos), `export_${selectedVideos.length}.csv`)}>{t('export.csv')}</button>
              <button className="btn-sm" onClick={() => downloadFile(videosToJson(selectedVideos), `export_${selectedVideos.length}.json`)}>{t('export.json')}</button>
              <button className="btn-sm" onClick={() => setSelectedIds(new Set())} style={{ marginLeft: 'auto' }}>{t('btn.cancelSelection')}</button>
            </div>
          )}
          <div className="table-scroll">
            <table className="video-table">
              <thead>
                <tr>
                  <th style={{ width: '30px', padding: '0.5rem 0.4rem' }}>
                    <input type="checkbox" checked={allSelected} ref={el => { if (el) el.indeterminate = someSelected && !allSelected; }} onChange={toggleSelectAll} style={{ width: 'auto', cursor: 'pointer' }} />
                  </th>
                  <th onClick={() => handleHeaderClick('title')} style={{ width: '43%' }}>
                    {t('label.title')}{renderSortIcon('title')}
                  </th>
                  <th onClick={() => handleHeaderClick('uploaded_at')} style={{ width: '11%' }}>
                    {t('label.uploadedAt')}{renderSortIcon('uploaded_at')}
                  </th>
                  <th onClick={() => handleHeaderClick('duration_seconds')} style={{ width: '7%' }}>
                    {t('label.duration')}{renderSortIcon('duration_seconds')}
                  </th>
                  <th onClick={() => handleHeaderClick('status')} style={{ width: '9%' }}>
                    {t('label.status')}{renderSortIcon('status')}
                  </th>
                  <th style={{ width: '25%' }}></th>
                </tr>
              </thead>
              <tbody>
                {videos.map((video, i) => {
                  const st = STATUS_MAP[video.status] || { icon: '', label: video.status };
                  const isSelected = selectedIds.has(video.id);
                  return (
                    <tr
                      key={video.id}
                      className={video.transcript ? 'clickable-row' : ''}
                      style={{ background: isSelected ? 'rgba(255,68,68,0.07)' : i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.02)' }}
                      onClick={() => video.transcript && onSelectVideo(video)}
                    >
                      <td style={{ padding: '0.5rem 0.4rem' }} onClick={e => { e.stopPropagation(); toggleSelect(video.id); }}>
                        <input type="checkbox" checked={isSelected} onChange={() => toggleSelect(video.id)} style={{ width: 'auto', cursor: 'pointer' }} />
                      </td>
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.55rem', minWidth: 0 }}>
                          {video.thumbnail_url && (
                            <img
                              src={video.thumbnail_url}
                              alt=""
                              loading="lazy"
                              style={{ width: '56px', height: '32px', objectFit: 'cover', borderRadius: '4px', flex: '0 0 auto', background: 'rgba(255,255,255,0.06)' }}
                            />
                          )}
                          <a
                            href={video.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="video-link"
                            title={video.title || t('state.unknownTitle')}
                            onClick={e => e.stopPropagation()}
                          >
                            {video.title || t('state.unknownTitle')}
                          </a>
                          {video.is_members_only && (
                            <span className="video-badge">{t('label.members')}</span>
                          )}
                        </div>
                      </td>
                      <td>{formatDate(video.uploaded_at)}</td>
                      <td>{formatDuration(video.duration_seconds)}</td>
                      <td>
                        <span className={`badge badge-${video.status}`}>
                          {st.icon} {st.label}
                        </span>
                        {video.quick_summary && !video.summary && (
                          <span
                            className="badge badge-pending"
                            title={video.quick_summary}
                            style={{ marginLeft: '0.35rem' }}
                          >
                            {t('status.quickDone')}
                          </span>
                        )}
                        {video.ai_notes_status && (
                          <span
                            className={`badge badge-${video.ai_notes_status}`}
                            title={video.ai_notes_error || ''}
                            style={{ marginLeft: '0.35rem' }}
                          >
                            {AI_STATUS_MAP[video.ai_notes_status] || video.ai_notes_status}
                          </span>
                        )}
                      </td>
                      <td>
                        <div className="video-row-actions">
                          {video.transcript && (
                            <button
                              className="btn-sm"
                              onClick={e => { e.stopPropagation(); onSelectVideo(video); }}
                            >
                              {t('btn.transcript')}
                            </button>
                          )}
                          {video.transcript && (
                            <button
                              className="btn-sm"
                              disabled={aiBusyId === video.id || video.ai_notes_status === 'pending'}
                              title={t('tooltip.generateQuick')}
                              onClick={e => handleGenerateQuickNote(e, video)}
                            >
                              {t('btn.quickNote')}
                            </button>
                          )}
                          {video.transcript && (
                            <button
                              className="btn-sm"
                              disabled={aiBusyId === video.id || video.ai_notes_status === 'pending'}
                              title={t('tooltip.generateAi')}
                              onClick={e => handleGenerateAiNote(e, video)}
                            >
                              {video.ai_notes_status === 'done' ? t('btn.aiRegen') : t('btn.aiNote')}
                            </button>
                          )}
                          {(video.summary || video.ai_notes_status) && (
                            <button
                              className="btn-sm danger"
                              disabled={aiBusyId === video.id}
                              title={t('tooltip.deleteAi')}
                              onClick={e => handleDeleteAiNote(e, video)}
                            >
                              {t('btn.aiDelete')}
                            </button>
                          )}
                          <div style={{ position: 'relative' }}>
                            <button
                              className="btn-sm"
                              onClick={e => {
                                e.stopPropagation();
                                setExportMenuId(prev => prev === video.id ? null : video.id);
                              }}
                            >
                              {t('export.label')} ▾
                            </button>
                            {exportMenuId === video.id && (
                              <div
                                className="export-menu"
                                onClick={e => e.stopPropagation()}
                              >
                                <button
                                  className="export-menu-item"
                                  onClick={() => { downloadFile(videoToTxt(video), `${sanitizeFilename(video.title)}.txt`); setExportMenuId(null); }}
                                >
                                  {t('export.txt')}
                                </button>
                                <button
                                  className="export-menu-item"
                                  onClick={() => { downloadFile(videoToMd(video), `${sanitizeFilename(video.title)}.md`); setExportMenuId(null); }}
                                >
                                  {t('export.md')}
                                </button>
                                <button
                                  className="export-menu-item"
                                  onClick={() => {
                                    downloadFile(
                                      videoToObsidianMd(video, { channel: selectedChannel, timed: true }),
                                      obsidianFilename(video, { channel: selectedChannel })
                                    );
                                    setExportMenuId(null);
                                  }}
                                >
                                  {t('export.obsidian')}
                                </button>
                                {(video.obsidian_note || video.summary) && (
                                  <button
                                    className="export-menu-item"
                                    onClick={() => {
                                      downloadFile(
                                        videoToMarkmapMd(video),
                                        markmapFilename(video, { channel: selectedChannel })
                                      );
                                      setExportMenuId(null);
                                    }}
                                  >
                                    {t('export.mindmap')}
                                  </button>
                                )}
                              </div>
                            )}
                          </div>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div ref={loadMoreRef} className="infinite-load">
            {loadingMore ? (
              <span>{t('state.loading')}</span>
            ) : hasMore ? (
              <button onClick={onLoadMore}>{t('state.loadMore')}</button>
            ) : (
              <span>{t('state.allLoaded', { count: videos.length, total: totalCount })}</span>
            )}
          </div>
        </>
      )}
    </div>
  );
}
