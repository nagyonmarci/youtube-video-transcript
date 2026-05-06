import { useState, useEffect, useCallback } from 'react';
import { getChannels, getVideos, getAllVideos, getTotalVideoCount } from './lib/directus.js';
import {
  stopProcessing, getStatus,
  getWhisperStatus, startWhisperBatch, stopWhisper, resumeWhisper,
} from './lib/fetcher.js';
import ChannelGrid from './components/ChannelGrid.jsx';
import VideoTable from './components/VideoTable.jsx';
import TranscriptModal from './components/TranscriptModal.jsx';
import DailyUpdatesPage from './components/DailyUpdatesPage.jsx';
import AdminDashboard from './components/AdminDashboard.jsx';

function sameData(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

function keepIfSame(prev, next) {
  return sameData(prev, next) ? prev : next;
}

export default function App() {
  const [channels, setChannels] = useState([]);
  const [selectedChannel, setSelectedChannel] = useState(null);
  const [videos, setVideos] = useState([]);
  const [totalCount, setTotalCount] = useState(0);
  const [allVideosCount, setAllVideosCount] = useState(0);
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState('-uploaded_at');
  const [search, setSearch] = useState('');
  const [selectedVideo, setSelectedVideo] = useState(null);
  const [fetcherStatus, setFetcherStatus] = useState(null);
  const [whisperStatus, setWhisperStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [view, setView] = useState('home');
  const selectedChannelId = selectedChannel?.id ?? null;

  const loadChannels = useCallback(async () => {
    try {
      const [data, total] = await Promise.all([
        getChannels(),
        getTotalVideoCount(),
      ]);
      setChannels(prev => keepIfSame(prev, data));
      setAllVideosCount(prev => (prev === total ? prev : total));
      setSelectedChannel(prev => {
        if (!prev) return prev;
        const next = data.find(ch => ch.id === prev.id) || null;
        if (!next) return null;
        return sameData(prev, next) ? prev : next;
      });
    } catch (e) {
      console.error('Failed to load channels', e);
    }
  }, []);

  const loadVideos = useCallback(async (showLoading = false) => {
    if (showLoading) setLoading(true);
    try {
      const opts = { sort, page, search };
      const result = selectedChannelId
        ? await getVideos(selectedChannelId, opts)
        : await getAllVideos(opts);
      setVideos(prev => keepIfSame(prev, result.items));
      setTotalCount(prev => (prev === result.total ? prev : result.total));
    } catch (e) {
      console.error('Failed to load videos', e);
    } finally {
      if (showLoading) setLoading(false);
    }
  }, [selectedChannelId, page, sort, search]);

  const loadStatus = useCallback(async () => {
    try {
      const s = await getStatus();
      setFetcherStatus(prev => keepIfSame(prev, s));
    } catch {
      setFetcherStatus(prev => (prev === null ? prev : null));
    }
    try {
      const w = await getWhisperStatus();
      setWhisperStatus(prev => keepIfSame(prev, w));
    } catch {
      setWhisperStatus(prev => (prev === null ? prev : null));
    }
  }, []);

  useEffect(() => {
    loadChannels();
    const interval = setInterval(() => {
      loadChannels();
      loadStatus();
    }, 10000);
    return () => clearInterval(interval);
  }, [loadChannels, loadStatus]);

  useEffect(() => {
    if (view !== 'home') return undefined;
    loadVideos(true);
    const interval = setInterval(() => loadVideos(false), 15000);
    return () => clearInterval(interval);
  }, [loadVideos, view]);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  // Reset page when channel or search changes
  function handleSelectChannel(ch) {
    setSelectedChannel(ch);
    setPage(1);
    setSearch('');
  }

  function handleSearchChange(value) {
    setSearch(value);
    setPage(1);
  }

  function handleSortChange(newSort) {
    setSort(newSort);
    setPage(1);
  }

  const handleStop = async () => {
    try {
      await stopProcessing();
      await loadStatus();
    } catch (e) {
      alert('Hiba: ' + e.message);
    }
  };

  const handleWhisperStart = async () => {
    try {
      const result = await startWhisperBatch();
      await loadStatus();
    } catch (e) {
      alert('Whisper hiba: ' + e.message);
    }
  };

  const handleWhisperStop = async () => {
    try {
      await stopWhisper();
      await loadStatus();
    } catch (e) {
      alert('Whisper hiba: ' + e.message);
    }
  };

  const whisperRunning = whisperStatus && (whisperStatus.queue_size > 0 || whisperStatus.batch_running);
  const fetcherRunning = fetcherStatus && (
    fetcherStatus.fetch_active_size > 0
    || fetcherStatus.ai_active_size > 0
    || fetcherStatus.queue_size > 0
    || fetcherStatus.ai_queue_size > 0
    || Boolean(fetcherStatus.current_task?.type)
    || Boolean(fetcherStatus.current_ai_task?.type)
  );

  return (
    <div className="app-layout">
      <header className="app-header">
        <span style={{ fontSize: '1.4rem' }}>▶</span>
        <h1 style={{ fontSize: '1.1rem', fontWeight: 700 }}>YouTube Transcript Downloader</h1>

        <nav className="main-nav">
          <button className={view === 'home' ? 'active' : ''} onClick={() => setView('home')}>Főoldal</button>
          <button className={view === 'daily' ? 'active' : ''} onClick={() => setView('daily')}>Napi frissítések</button>
          <button className={view === 'admin' ? 'active' : ''} onClick={() => setView('admin')}>Admin</button>
        </nav>

        <div className="header-status">
          {/* Fetcher status */}
          {fetcherRunning && (
            <span className="header-status-item">
              <span className="badge badge-processing">
                Feldolgozás: {fetcherStatus.queue_size} a sorban
                {fetcherStatus.current_task?.phase && ` • ${fetcherStatus.current_task.phase}`}
                {fetcherStatus.current_task?.video && ` • ${fetcherStatus.current_task.video}`}
                {(fetcherStatus.ai_active_size > 0 || fetcherStatus.ai_queue_size > 0) && ` • AI aktív: ${fetcherStatus.ai_active_size ?? fetcherStatus.ai_queue_size}`}
                {fetcherStatus.current_ai_task?.phase && ` • ${fetcherStatus.current_ai_task.phase}`}
                {fetcherStatus.current_ai_task?.video && ` • ${fetcherStatus.current_ai_task.video}`}
              </span>
              <button className="danger" onClick={handleStop} style={{ padding: '0.25rem 0.6rem' }}>
                Stop
              </button>
            </span>
          )}

          {/* Whisper status & controls */}
          <span className="header-status-item">
            {whisperRunning ? (
              <>
                <span className="badge badge-whisper">
                  🎙 Whisper: {whisperStatus.queue_size} a sorban
                  {whisperStatus.current_task?.video_id && ` • ${whisperStatus.current_task.video_id}`}
                  {whisperStatus.current_task?.phase && ` (${whisperStatus.current_task.phase})`}
                </span>
                <button className="danger" onClick={handleWhisperStop} style={{ padding: '0.25rem 0.6rem' }}>
                  Stop
                </button>
              </>
            ) : (
              <button onClick={handleWhisperStart} className="whisper-btn" style={{ padding: '0.25rem 0.6rem' }}>
                🎙 Whisper indítás
              </button>
            )}
          </span>
        </div>
      </header>

      <div className="app-content">
        {view === 'home' && (
          <>
            <ChannelGrid
              channels={channels}
              totalVideos={allVideosCount}
              selectedChannel={selectedChannel}
              onSelect={handleSelectChannel}
              onChannelsChanged={async () => {
                await loadChannels();
                await loadVideos(false);
              }}
            />

            <VideoTable
              videos={videos}
              totalCount={totalCount}
              page={page}
              onPageChange={setPage}
              search={search}
              onSearchChange={handleSearchChange}
              sort={sort}
              onSortChange={handleSortChange}
              loading={loading}
              onSelectVideo={video => setSelectedVideo({ ...video, channel: selectedChannel || video.channel_id })}
              onVideosChanged={() => loadVideos(false)}
              selectedChannel={selectedChannel}
            />
          </>
        )}

        {view === 'daily' && (
          <DailyUpdatesPage
            onSelectVideo={video => setSelectedVideo({ ...video, channel: video.channel_id })}
          />
        )}

        {view === 'admin' && (
          <AdminDashboard
            channels={channels}
            selectedChannel={selectedChannel}
            fetcherStatus={fetcherStatus}
            whisperStatus={whisperStatus}
            onStatusChanged={loadStatus}
            onChannelsChanged={async () => {
              await loadChannels();
              await loadVideos(false);
            }}
          />
        )}
      </div>

      {selectedVideo && (
        <TranscriptModal
          video={selectedVideo}
          onClose={() => setSelectedVideo(null)}
        />
      )}
    </div>
  );
}
