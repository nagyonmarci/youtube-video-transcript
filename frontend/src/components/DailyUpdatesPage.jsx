import { useEffect, useMemo, useState } from 'react';
import { getDailyVideos } from '../lib/directus.js';
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

function groupByChannel(videos) {
  return videos.reduce((groups, video) => {
    const channel = video.channel_id;
    const key = channel?.name || channel?.channel_handle || '';
    if (!groups[key]) groups[key] = { label: key, videos: [] };
    groups[key].videos.push(video);
    return groups;
  }, {});
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
  const [date, setDate] = useState(todayValue());
  const [videos, setVideos] = useState([]);
  const [filter, setFilter] = useState('all');
  const [titleSearch, setTitleSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState(null);
  const { msg, showMsg } = useMessage();

  async function load() {
    setLoading(true);
    try {
      setVideos(await getDailyVideos(date, LOCAL_TIMEZONE));
    } catch (e) {
      showMsg(t('msg.errDaily', { error: e.message }), true);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [date]);

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

  const groups = useMemo(() => groupByChannel(filteredVideos), [filteredVideos]);
  const groupEntries = Object.entries(groups).sort(([a], [b]) => a.localeCompare(b, 'hu'));

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

  function changeDay(delta) {
    const current = new Date(`${date}T00:00:00`);
    current.setDate(current.getDate() + delta);
    setDate([
      current.getFullYear(),
      String(current.getMonth() + 1).padStart(2, '0'),
      String(current.getDate()).padStart(2, '0'),
    ].join('-'));
  }

  return (
    <section className="daily-page">
      <div className="view-header">
        <div>
          <h2>{t('header.daily')}</h2>
          <p>{t('header.dailySub', { count: filteredVideos.length })}</p>
        </div>
        <div className="daily-controls">
          <button onClick={() => changeDay(-1)}>{t('btn.prevDay')}</button>
          <input type="date" value={date} onChange={e => setDate(e.target.value)} />
          <button onClick={() => setDate(todayValue())}>{t('btn.today')}</button>
          <button onClick={() => changeDay(1)}>{t('btn.nextDay')}</button>
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
      ) : groupEntries.length === 0 ? (
        <div className="video-empty">{t('state.noVideos')}</div>
      ) : (
        <div className="daily-groups">
          {groupEntries.map(([key, group]) => (
            <section key={key} className="daily-channel">
              <div className="daily-channel-header">
                <h3>{group.label || t('state.unknownChannel')}</h3>
                <span>{t('label.videoCount', { count: group.videos.length })}</span>
              </div>
              <div className="daily-video-list">
                {group.videos.map(video => (
                  <article key={video.id} className="daily-video-card">
                    <div className="daily-video-main">
                      <a href={video.url} target="_blank" rel="noopener noreferrer" className="daily-video-title">
                        {video.title || t('state.unknownTitle')}
                      </a>
                      <div className="daily-video-meta">
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
            </section>
          ))}
        </div>
      )}
    </section>
  );
}
