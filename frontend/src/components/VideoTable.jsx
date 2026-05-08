import { useState, useEffect, useRef, useCallback } from 'react';
import { deleteAiNoteForVideo, generateAiNoteForVideo } from '../lib/fetcher.js';
import { videoToTxt, videoToMd, videoToObsidianMd, obsidianFilename, videoToMarkmapMd, markmapFilename, downloadFile, sanitizeFilename, videosToCsv, videosToJson } from '../lib/export.js';

async function bulkGenerateAiNotes(videos) {
  for (const v of videos) {
    try { await generateAiNoteForVideo(v.id); } catch {}
  }
}

async function bulkDeleteAiNotes(videos) {
  for (const v of videos) {
    try { await deleteAiNoteForVideo(v.id); } catch {}
  }
}

function formatDuration(seconds) {
  if (!seconds) return '—';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${m}:${String(s).padStart(2, '0')}`;
}

function formatDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('hu-HU');
}

const STATUS_MAP = {
  done: { icon: '✅', label: 'Kész' },
  pending: { icon: '⏳', label: 'Várakozik' },
  processing: { icon: '🔄', label: 'Feldolgozás' },
  no_transcript: { icon: '—', label: 'Nincs' },
  error: { icon: '⚠️', label: 'Hiba' },
};

const AI_STATUS_MAP = {
  done: 'AI kész',
  pending: 'AI folyamatban',
  error: 'AI hiba',
};

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
}) {
  const searchInputRef = useRef();
  const [localSearch, setLocalSearch] = useState(search);
  const [aiBusyId, setAiBusyId] = useState(null);
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const debounceRef = useRef(null);
  const loadMoreRef = useRef(null);

  useEffect(() => { setSelectedIds(new Set()); }, [search, statusFilter, aiFilter, membersFilter, sort, selectedChannel?.id]);

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
      await bulkGenerateAiNotes(selectedVideos.filter(v => v.transcript));
      await onVideosChanged?.();
    } finally {
      setBulkBusy(false);
    }
  }

  async function handleBulkDeleteAi() {
    if (!selectedVideos.length) return;
    if (!confirm(`Töröljük az AI noteket ${selectedVideos.length} videóhoz?`)) return;
    setBulkBusy(true);
    try {
      await bulkDeleteAiNotes(selectedVideos);
      await onVideosChanged?.();
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

  // Sync local search with prop
  useEffect(() => {
    setLocalSearch(search);
  }, [search]);

  const handleSearchInput = useCallback((e) => {
    const value = e.target.value;
    setLocalSearch(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      onSearchChange(value);
    }, 300);
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

  async function handleGenerateAiNote(e, video) {
    e.stopPropagation();
    setAiBusyId(video.id);
    try {
      await generateAiNoteForVideo(video.id);
    } catch (err) {
      alert('AI jegyzet hiba: ' + err.message);
    } finally {
      setAiBusyId(null);
    }
  }

  async function handleDeleteAiNote(e, video) {
    e.stopPropagation();
    if (!confirm(`Töröljük az AI jegyzetet ehhez a videóhoz?\n\n${video.title || video.video_id}`)) return;
    setAiBusyId(video.id);
    try {
      await deleteAiNoteForVideo(video.id);
      await onVideosChanged?.();
    } catch (err) {
      alert('AI jegyzet törlés hiba: ' + err.message);
    } finally {
      setAiBusyId(null);
    }
  }

  return (
    <div className="video-section">
      <div className="video-header">
        <h2 className="video-title">
          {selectedChannel
            ? `${selectedChannel.name || selectedChannel.channel_handle} — ${totalCount} videó`
            : `Összes videó (${totalCount})`
          }
        </h2>
        <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center', flexWrap: 'wrap' }}>
          <input
            ref={searchInputRef}
            className="video-search"
            placeholder="Cím keresés..."
            value={localSearch}
            onChange={handleSearchInput}
            style={{ width: '200px' }}
          />
          <select
            value={statusFilter}
            onChange={e => onStatusFilterChange?.(e.target.value)}
            style={{ width: 'auto' }}
            title="Transzkript állapot szűrő"
          >
            <option value="all">Minden állapot</option>
            <option value="done">Kész</option>
            <option value="pending">Várakozik</option>
            <option value="no_transcript">Nincs transzkript</option>
            <option value="error">Hiba</option>
          </select>
          <select
            value={aiFilter}
            onChange={e => onAiFilterChange?.(e.target.value)}
            style={{ width: 'auto' }}
            title="AI jegyzetek szűrő"
          >
            <option value="all">Minden AI</option>
            <option value="done">AI kész</option>
            <option value="missing">AI hiányzik</option>
            <option value="error">AI hiba</option>
          </select>
          <select
            value={membersFilter}
            onChange={e => onMembersFilterChange?.(e.target.value)}
            style={{ width: 'auto' }}
            title="Members-only videók szűrője"
          >
            <option value="all">Members: mind</option>
            <option value="hide">Members elrejtve</option>
            <option value="only">Csak members</option>
          </select>
        </div>
      </div>

      {loading ? (
        <div className="video-empty">Betöltés...</div>
      ) : totalCount === 0 ? (
        <div className="video-empty">
          {search ? 'Nincs találat.' : 'Nincsenek videók. Adj hozzá egy csatornát fent.'}
        </div>
      ) : (
        <>
          {someSelected && (
            <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center', padding: '0.4rem 0.5rem', background: 'var(--primary-dim)', border: '1px solid var(--primary)', borderRadius: '6px', marginBottom: '0.4rem', flexWrap: 'wrap' }}>
              <span style={{ fontSize: '0.82rem', fontWeight: 600 }}>{selectedIds.size} kiválasztva</span>
              <button className="btn-sm" disabled={bulkBusy} onClick={handleBulkAiNotes} title="AI notes generálás a kiválasztottakhoz">AI generálás</button>
              <button className="btn-sm danger" disabled={bulkBusy} onClick={handleBulkDeleteAi}>AI törlés</button>
              <button className="btn-sm" disabled={bulkBusy} onClick={handleBulkExportMd}>MD letöltés</button>
              <button className="btn-sm" disabled={bulkBusy} onClick={handleBulkExportObsidian}>Obsidian letöltés</button>
              <button className="btn-sm" onClick={() => downloadFile(videosToCsv(selectedVideos), `export_${selectedVideos.length}.csv`)}>CSV</button>
              <button className="btn-sm" onClick={() => downloadFile(videosToJson(selectedVideos), `export_${selectedVideos.length}.json`)}>JSON</button>
              <button className="btn-sm" onClick={() => setSelectedIds(new Set())} style={{ marginLeft: 'auto' }}>✕ Visszavonás</button>
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
                    Cím{renderSortIcon('title')}
                  </th>
                  <th onClick={() => handleHeaderClick('uploaded_at')} style={{ width: '11%' }}>
                    Feltöltve{renderSortIcon('uploaded_at')}
                  </th>
                  <th onClick={() => handleHeaderClick('duration_seconds')} style={{ width: '7%' }}>
                    Hossz{renderSortIcon('duration_seconds')}
                  </th>
                  <th onClick={() => handleHeaderClick('status')} style={{ width: '9%' }}>
                    Állapot{renderSortIcon('status')}
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
                            title={video.title || 'Ismeretlen'}
                            onClick={e => e.stopPropagation()}
                          >
                            {video.title || 'Ismeretlen'}
                          </a>
                          {video.is_members_only && (
                            <span className="video-badge">Members</span>
                          )}
                        </div>
                      </td>
                      <td>{formatDate(video.uploaded_at)}</td>
                      <td>{formatDuration(video.duration_seconds)}</td>
                      <td>
                        <span className={`badge badge-${video.status}`}>
                          {st.icon} {st.label}
                        </span>
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
                        <div style={{ display: 'flex', gap: '0.3rem' }}>
                          {video.transcript && (
                            <button
                              className="btn-sm"
                              onClick={e => { e.stopPropagation(); onSelectVideo(video); }}
                            >
                              Transzkript
                            </button>
                          )}
                          {video.transcript && (
                            <button
                              className="btn-sm"
                              disabled={aiBusyId === video.id || video.ai_notes_status === 'pending'}
                              title="AI összefoglaló, témák, tanulságok, kérdések és Obsidian jegyzet generálása"
                              onClick={e => handleGenerateAiNote(e, video)}
                            >
                              {video.ai_notes_status === 'done' ? 'AI újra' : 'AI jegyzet'}
                            </button>
                          )}
                          {(video.summary || video.ai_notes_status) && (
                            <button
                              className="btn-sm danger"
                              disabled={aiBusyId === video.id}
                              title="A generált AI jegyzet mezők törlése"
                              onClick={e => handleDeleteAiNote(e, video)}
                            >
                              AI törlés
                            </button>
                          )}
                          <button
                            className="btn-sm"
                            onClick={e => {
                              e.stopPropagation();
                              downloadFile(videoToTxt(video), `${sanitizeFilename(video.title)}.txt`);
                            }}
                          >
                            TXT
                          </button>
                          <button
                            className="btn-sm"
                            onClick={e => {
                              e.stopPropagation();
                              downloadFile(videoToMd(video), `${sanitizeFilename(video.title)}.md`);
                            }}
                          >
                            MD
                          </button>
                          <button
                            className="btn-sm"
                            onClick={e => {
                              e.stopPropagation();
                              downloadFile(
                                videoToObsidianMd(video, { channel: selectedChannel, timed: true }),
                                obsidianFilename(video, { channel: selectedChannel })
                              );
                            }}
                          >
                            Obsidian
                          </button>
                          {(video.obsidian_note || video.summary) && (
                            <button
                              className="btn-sm"
                              title="Markmap gondolattérkép letöltése (Obsidian markmap plugin szükséges)"
                              onClick={e => {
                                e.stopPropagation();
                                downloadFile(
                                  videoToMarkmapMd(video),
                                  markmapFilename(video, { channel: selectedChannel })
                                );
                              }}
                            >
                              Mindmap
                            </button>
                          )}
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
              <span>Betöltés...</span>
            ) : hasMore ? (
              <button onClick={onLoadMore}>További videók betöltése</button>
            ) : (
              <span>Mind betöltve ({videos.length} / {totalCount})</span>
            )}
          </div>
        </>
      )}
    </div>
  );
}
