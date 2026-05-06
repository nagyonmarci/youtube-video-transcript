import { useState, useEffect, useRef, useCallback } from 'react';
import { deleteAiNoteForVideo, generateAiNoteForVideo } from '../lib/fetcher.js';
import { videoToTxt, videoToMd, videoToObsidianMd, obsidianFilename, videoToMarkmapMd, markmapFilename, downloadFile, sanitizeFilename } from '../lib/export.js';

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

const PAGE_SIZE = 100;

export default function VideoTable({
  videos,
  totalCount,
  page,
  onPageChange,
  search,
  onSearchChange,
  sort,
  onSortChange,
  loading,
  onSelectVideo,
  selectedChannel,
}) {
  const searchInputRef = useRef();
  const [localSearch, setLocalSearch] = useState(search);
  const [aiBusyId, setAiBusyId] = useState(null);
  const debounceRef = useRef(null);

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

  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE));

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
        <input
          ref={searchInputRef}
          className="video-search"
          placeholder="Keresés..."
          value={localSearch}
          onChange={handleSearchInput}
        />
      </div>

      {loading ? (
        <div className="video-empty">Betöltés...</div>
      ) : totalCount === 0 ? (
        <div className="video-empty">
          {search ? 'Nincs találat.' : 'Nincsenek videók. Adj hozzá egy csatornát fent.'}
        </div>
      ) : (
        <>
          <div className="table-scroll">
            <table className="video-table">
              <thead>
                <tr>
                  <th onClick={() => handleHeaderClick('title')} style={{ width: '45%' }}>
                    Cím{renderSortIcon('title')}
                  </th>
                  <th onClick={() => handleHeaderClick('uploaded_at')} style={{ width: '12%' }}>
                    Feltöltve{renderSortIcon('uploaded_at')}
                  </th>
                  <th onClick={() => handleHeaderClick('duration_seconds')} style={{ width: '8%' }}>
                    Hossz{renderSortIcon('duration_seconds')}
                  </th>
                  <th onClick={() => handleHeaderClick('status')} style={{ width: '10%' }}>
                    Állapot{renderSortIcon('status')}
                  </th>
                  <th style={{ width: '25%' }}></th>
                </tr>
              </thead>
              <tbody>
                {videos.map((video, i) => {
                  const st = STATUS_MAP[video.status] || { icon: '', label: video.status };
                  return (
                    <tr
                      key={video.id}
                      className={video.transcript ? 'clickable-row' : ''}
                      style={{ background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.02)' }}
                      onClick={() => video.transcript && onSelectVideo(video)}
                    >
                      <td>
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

          {/* Pagination */}
          <div className="pagination">
            <button
              disabled={page <= 1}
              onClick={() => onPageChange(page - 1)}
            >
              ← Előző
            </button>
            <span className="page-info">
              {page} / {totalPages} oldal
            </span>
            <button
              disabled={page >= totalPages}
              onClick={() => onPageChange(page + 1)}
            >
              Következő →
            </button>
          </div>
        </>
      )}
    </div>
  );
}
