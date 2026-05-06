import { useEffect, useMemo, useState } from 'react';
import { getDailyVideos } from '../lib/directus.js';
import { generateAiNoteForVideo } from '../lib/fetcher.js';
import { downloadFile, obsidianFilename, sanitizeFilename, videoToMd, videoToObsidianMd, videoToMarkmapMd, markmapFilename } from '../lib/export.js';

function todayValue() {
  const now = new Date();
  return [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, '0'),
    String(now.getDate()).padStart(2, '0'),
  ].join('-');
}

function formatDateTime(iso) {
  if (!iso) return 'Nincs dátum';
  return new Date(iso).toLocaleString('hu-HU', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function channelName(video) {
  const channel = video.channel_id;
  return channel?.name || channel?.channel_handle || 'Ismeretlen csatorna';
}

function groupByChannel(videos) {
  return videos.reduce((groups, video) => {
    const key = channelName(video);
    if (!groups[key]) groups[key] = [];
    groups[key].push(video);
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
  const [date, setDate] = useState(todayValue());
  const [videos, setVideos] = useState([]);
  const [filter, setFilter] = useState('all');
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState(null);
  const [msg, setMsg] = useState(null);

  async function load() {
    setLoading(true);
    try {
      setVideos(await getDailyVideos(date));
    } catch (e) {
      setMsg({ text: 'Napi frissítés betöltési hiba: ' + e.message, isError: true });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [date]);

  function showMsg(text, isError = false) {
    setMsg({ text, isError });
    setTimeout(() => setMsg(null), 4000);
  }

  const filteredVideos = useMemo(() => {
    if (filter === 'with_ai') return videos.filter(video => video.summary || video.ai_notes_status === 'done');
    if (filter === 'without_ai') return videos.filter(video => video.transcript && !video.summary);
    if (filter === 'without_transcript') return videos.filter(video => !video.transcript);
    return videos;
  }, [videos, filter]);

  const groups = useMemo(() => groupByChannel(filteredVideos), [filteredVideos]);
  const groupEntries = Object.entries(groups).sort(([a], [b]) => a.localeCompare(b, 'hu'));

  async function handleGenerateAi(video) {
    setBusyId(video.id);
    try {
      await generateAiNoteForVideo(video.id);
      showMsg('AI jegyzet sorba állítva');
      await load();
    } catch (e) {
      showMsg('AI jegyzet hiba: ' + e.message, true);
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
          <h2>Napi frissítések</h2>
          <p>{filteredVideos.length} videó ezen a napon</p>
        </div>
        <div className="daily-controls">
          <button onClick={() => changeDay(-1)}>Előző nap</button>
          <input type="date" value={date} onChange={e => setDate(e.target.value)} />
          <button onClick={() => setDate(todayValue())}>Ma</button>
          <button onClick={() => changeDay(1)}>Következő nap</button>
          <select value={filter} onChange={e => setFilter(e.target.value)}>
            <option value="all">Összes</option>
            <option value="with_ai">AI kész</option>
            <option value="without_ai">AI hiányzik</option>
            <option value="without_transcript">Transzkript hiányzik</option>
          </select>
        </div>
      </div>

      {msg && <div className={`status-msg ${msg.isError ? 'status-error' : 'status-success'}`}>{msg.text}</div>}

      {loading ? (
        <div className="video-empty">Betöltés...</div>
      ) : groupEntries.length === 0 ? (
        <div className="video-empty">Nincs videó a választott napon.</div>
      ) : (
        <div className="daily-groups">
          {groupEntries.map(([name, channelVideos]) => (
            <section key={name} className="daily-channel">
              <div className="daily-channel-header">
                <h3>{name}</h3>
                <span>{channelVideos.length} videó</span>
              </div>
              <div className="daily-video-list">
                {channelVideos.map(video => (
                  <article key={video.id} className="daily-video-card">
                    <div className="daily-video-main">
                      <a href={video.url} target="_blank" rel="noopener noreferrer" className="daily-video-title">
                        {video.title || 'Ismeretlen cím'}
                      </a>
                      <div className="daily-video-meta">
                        <span>{formatDateTime(video.uploaded_at)}</span>
                        <span className={`badge badge-${video.status}`}>{video.status || 'nincs státusz'}</span>
                        {video.ai_notes_status && (
                          <span className={`badge badge-${video.ai_notes_status}`}>{video.ai_notes_status}</span>
                        )}
                      </div>
                      {video.summary ? (
                        <p className="daily-summary">{video.summary}</p>
                      ) : (
                        <p className="daily-summary daily-muted">Még nincs AI összefoglaló.</p>
                      )}
                      {video.topics?.length > 0 && (
                        <div className="topic-row">
                          {video.topics.slice(0, 6).map(topic => <span key={topic}>{topic}</span>)}
                        </div>
                      )}
                      {listPreview(video.takeaways)}
                    </div>
                    <div className="daily-video-actions">
                      {video.transcript && <button onClick={() => onSelectVideo(video)}>Transzkript</button>}
                      {video.transcript && (
                        <button disabled={busyId === video.id || video.ai_notes_status === 'pending'} onClick={() => handleGenerateAi(video)}>
                          {video.summary ? 'AI újra' : 'AI jegyzet'}
                        </button>
                      )}
                      <button
                        onClick={() => downloadFile(videoToMd(video, { timed: true }), `${sanitizeFilename(video.title)}.md`)}
                      >
                        MD
                      </button>
                      <button
                        onClick={() => downloadFile(videoToObsidianMd(video, { timed: true }), obsidianFilename(video))}
                      >
                        Obsidian
                      </button>
                      {(video.obsidian_note || video.summary) && (
                        <button
                          title="Markmap gondolattérkép letöltése (Obsidian markmap plugin szükséges)"
                          onClick={() => downloadFile(videoToMarkmapMd(video), markmapFilename(video))}
                        >
                          Mindmap
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
