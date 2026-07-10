import { useEffect, useMemo, useState } from 'react';
import { getVideosInRange } from '../lib/directus.js';
import { generateAiNoteForVideo } from '../lib/fetcher.js';
import { downloadFile, obsidianFilename, sanitizeFilename, videoToMd, videoToObsidianMd, videoToMarkmapMd, markmapFilename } from '../lib/export.js';
import { useT } from '../lib/i18n.jsx';
import { useMessage } from '../lib/useMessage.js';
import { DEFAULT_TIMEZONE } from '../lib/constants.js';

const LOCAL_TIMEZONE = Intl.DateTimeFormat().resolvedOptions().timeZone || DEFAULT_TIMEZONE;

function todayValue() {
  const now = new Date();
  return [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, '0'),
    String(now.getDate()).padStart(2, '0'),
  ].join('-');
}

function shiftDate(dateStr, delta) {
  const d = new Date(`${dateStr}T00:00:00`);
  d.setDate(d.getDate() + delta);
  return [d.getFullYear(), String(d.getMonth() + 1).padStart(2, '0'), String(d.getDate()).padStart(2, '0')].join('-');
}

function defaultDateFrom() {
  return shiftDate(todayValue(), -6);
}

function formatDateTime(iso) {
  if (!iso) return '';
  return new Date(iso).toLocaleString('hu-HU', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function channelLabel(video) {
  return video.channel_id?.name || video.channel_id?.channel_handle || '';
}

function listPreview(items, limit = 3) {
  if (!Array.isArray(items) || items.length === 0) return null;
  return (
    <ul className="daily-list">
      {items.slice(0, limit).map((item, index) => <li key={index}>{item}</li>)}
    </ul>
  );
}

export default function DailyUpdatesPage({ onSelectVideo }) {
  const { t } = useT();
  const [dateFrom, setDateFrom] = useState(defaultDateFrom());
  const [dateTo, setDateTo] = useState(todayValue());
  const [videos, setVideos] = useState([]);
  const [filter, setFilter] = useState('all');
  const [titleSearch, setTitleSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState(null);
  const { msg, showMsg } = useMessage();

  async function load() {
    setLoading(true);
    try {
      setVideos(await getVideosInRange(dateFrom, dateTo, LOCAL_TIMEZONE));
    } catch (e) {
      showMsg(t('msg.errDaily', { error: e.message }), true);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [dateFrom, dateTo]);

  const filteredVideos = useMemo(() => {
    let result = videos;
    if (filter === 'with_ai') result = result.filter(v => v.summary || v.ai_notes_status === 'done');
    else if (filter === 'without_ai') result = result.filter(v => v.transcript && !v.summary);
    else if (filter === 'without_transcript') result = result.filter(v => !v.transcript);
    if (titleSearch.trim()) {
      const q = titleSearch.trim().toLowerCase();
      result = result.filter(v => (v.title || '').toLowerCase().includes(q));
    }
    return result;
  }, [videos, filter, titleSearch]);

  async function handleGenerateAi(video) {
    setBusyId(video.id);
    try {
      await generateAiNoteForVideo(video.id);
      showMsg(t('msg.aiQueued', { count: 1 }));
      await load();
    } catch (e) {
      showMsg(t('msg.errAi', { error: e.message }), true);
    } finally {
      setBusyId(null);
    }
  }

  function resetToLastWeek() {
    setDateFrom(defaultDateFrom());
    setDateTo(todayValue());
  }

  return (
    <section className="daily-page">
      <div className="view-header">
        <div>
          <h2>{t('header.daily')}</h2>
          <p>{t('header.dailySub', { count: filteredVideos.length })}</p>
        </div>
        <div className="daily-controls">
          <label>{t('label.dateFrom')} <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} /></label>
          <label>{t('label.dateTo')} <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} /></label>
          <button onClick={resetToLastWeek}>{t('btn.lastWeek')}</button>
          <select value={filter} onChange={e => setFilter(e.target.value)}>
            <option value="all">{t('filter.all')}</option>
            <option value="with_ai">{t('filter.aiDone')}</option>
            <option value="without_ai">{t('filter.aiMissing')}</option>
            <option value="without_transcript">{t('filter.transcriptMissing')}</option>
          </select>
          <input
            type="search"
            placeholder={t('placeholder.searchVideo')}
            value={titleSearch}
            onChange={e => setTitleSearch(e.target.value)}
            style={{ width: '180px' }}
          />
        </div>
      </div>

      {msg && <div className={`status-msg ${msg.isError ? 'status-error' : 'status-success'}`}>{msg.text}</div>}

      {loading ? (
        <div className="video-empty">{t('state.loading')}</div>
      ) : filteredVideos.length === 0 ? (
        <div className="video-empty">{t('state.noVideos')}</div>
      ) : (
        <div className="daily-video-list">
          {filteredVideos.map(video => (
            <article key={video.id} className="daily-video-card">
              {video.thumbnail_url && (
                <img
                  src={video.thumbnail_url}
                  alt=""
                  loading="lazy"
                  style={{ width: '100%', height: '180px', objectFit: 'cover', borderRadius: '6px', background: 'rgba(255,255,255,0.06)' }}
                />
              )}
              <div className="daily-video-main">
                <a href={video.url} target="_blank" rel="noopener noreferrer" className="daily-video-title">
                  {video.title || t('state.unknownTitle')}
                </a>
                <div className="daily-video-meta">
                  <span>{channelLabel(video) || t('state.unknownChannel')}</span>
                  <span>{formatDateTime(video.uploaded_at)}</span>
                  <span className={`badge badge-${video.status}`}>{video.status}</span>
                  {video.ai_notes_status && (
                    <span className={`badge badge-${video.ai_notes_status}`}>{video.ai_notes_status}</span>
                  )}
                </div>
                {video.summary ? (
                  <p className="daily-summary">{video.summary}</p>
                ) : (
                  <p className="daily-summary daily-muted">{t('state.noAiSummary')}</p>
                )}
                {video.topics?.length > 0 && (
                  <div className="topic-row">
                    {video.topics.slice(0, 6).map(topic => <span key={topic}>{topic}</span>)}
                  </div>
                )}
                {listPreview(video.takeaways)}
              </div>
              <div className="daily-video-actions">
                {video.transcript && <button onClick={() => onSelectVideo(video)}>{t('btn.transcript')}</button>}
                {video.transcript && (
                  <button disabled={busyId === video.id || video.ai_notes_status === 'pending'} onClick={() => handleGenerateAi(video)}>
                    {video.summary ? t('btn.aiRegen') : t('btn.aiNote')}
                  </button>
                )}
                <button
                  onClick={() => downloadFile(videoToMd(video, { timed: true }), `${sanitizeFilename(video.title)}.md`)}
                >
                  {t('export.md')}
                </button>
                <button
                  onClick={() => downloadFile(videoToObsidianMd(video, { timed: true }), obsidianFilename(video))}
                >
                  {t('export.obsidian')}
                </button>
                {(video.obsidian_note || video.summary) && (
                  <button
                    title={t('tooltip.mindmap')}
                    onClick={() => downloadFile(videoToMarkmapMd(video), markmapFilename(video))}
                  >
                    {t('export.mindmap')}
                  </button>
                )}
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
