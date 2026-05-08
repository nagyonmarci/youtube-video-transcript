import { useState, useEffect, useCallback, useRef } from 'react';
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

function readUrlFilters() {
  const p = new URLSearchParams(window.location.search);
  return {
    search: p.get('q') || '',
    statusFilter: p.get('status') || 'all',
    aiFilter: p.get('ai') || 'all',
    membersFilter: p.get('members') || 'all',
  };
}

export default function App() {
  const [channels, setChannels] = useState([]);
  const [selectedChannel, setSelectedChannel] = useState(null);
  const [videos, setVideos] = useState([]);
  const [totalCount, setTotalCount] = useState(0);
  const [allVideosCount, setAllVideosCount] = useState(0);
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState('-uploaded_at');
  const initialFilters = readUrlFilters();
  const [search, setSearch] = useState(initialFilters.search);
  const [statusFilter, setStatusFilter] = useState(initialFilters.statusFilter);
  const [aiFilter, setAiFilter] = useState(initialFilters.aiFilter);
  const [membersFilter, setMembersFilter] = useState(initialFilters.membersFilter);
  const [selectedVideo, setSelectedVideo] = useState(null);
  const [fetcherStatus, setFetcherStatus] = useState(null);
  const [whisperStatus, setWhisperStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [view, setView] = useState('home');
  const [toasts, setToasts] = useState([]);
  const [showScrollTop, setShowScrollTop] = useState(false);
  const appContentRef = useRef(null);
  const prevFetcherRunning = useRef(false);
  const prevWhisperRunning = useRef(false);
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

  useEffect(() => {
    const p = new URLSearchParams();
    if (search) p.set('q', search);
    if (statusFilter !== 'all') p.set('status', statusFilter);
    if (aiFilter !== 'all') p.set('ai', aiFilter);
    if (membersFilter !== 'all') p.set('members', membersFilter);
    const qs = p.toString();
    window.history.replaceState({}, '', qs ? `?${qs}` : window.location.pathname);
  }, [search, statusFilter, aiFilter, membersFilter]);

  const loadVideos = useCallback(async ({ showLoading = false, targetPage = page, append = false } = {}) => {
    if (showLoading) setLoading(true);
    if (append) setLoadingMore(true);
    try {
      const opts = { sort, page: targetPage, search, statusFilter, aiFilter, membersFilter };
      const result = selectedChannelId
        ? await getVideos(selectedChannelId, opts)
        : await getAllVideos(opts);
      setVideos(prev => {
        if (!append) return keepIfSame(prev, result.items);
        const seen = new Set(prev.map(v => v.id));
        const merged = [...prev, ...result.items.filter(v => !seen.has(v.id))];
        return keepIfSame(prev, merged);
      });
      setTotalCount(prev => (prev === result.total ? prev : result.total));
    } catch (e) {
      console.error('Failed to load videos', e);
    } finally {
      if (showLoading) setLoading(false);
      if (append) setLoadingMore(false);
    }
  }, [selectedChannelId, page, sort, search, statusFilter, aiFilter, membersFilter]);

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
    loadVideos({ showLoading: page === 1, targetPage: page, append: page > 1 });
    return undefined;
  }, [loadVideos, page, view]);

  useEffect(() => {
    const el = appContentRef.current;
    const handleScroll = () => {
      const contentTop = el?.scrollTop ?? 0;
      const windowTop = window.scrollY || document.documentElement.scrollTop || document.body.scrollTop || 0;
      setShowScrollTop(Math.max(contentTop, windowTop) > 180);
    };
    handleScroll();
    el?.addEventListener('scroll', handleScroll, { passive: true });
    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => {
      el?.removeEventListener('scroll', handleScroll);
      window.removeEventListener('scroll', handleScroll);
    };
  }, []);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  const whisperRunning = whisperStatus && (whisperStatus.queue_size > 0 || whisperStatus.batch_running);
  const fetcherRunning = fetcherStatus && (
    fetcherStatus.fetch_active_size > 0
    || fetcherStatus.ai_active_size > 0
    || fetcherStatus.queue_size > 0
    || fetcherStatus.ai_queue_size > 0
    || Boolean(fetcherStatus.current_task?.type)
    || Boolean(fetcherStatus.current_ai_task?.type)
  );

  useEffect(() => {
    if (prevFetcherRunning.current && !fetcherRunning) addToast('Feldolgozás kész.');
    prevFetcherRunning.current = !!fetcherRunning;
  }, [fetcherRunning]);

  useEffect(() => {
    if (prevWhisperRunning.current && !whisperRunning) addToast('Whisper átírás kész.');
    prevWhisperRunning.current = !!whisperRunning;
  }, [whisperRunning]);

  function handleSelectChannel(ch) {
    setSelectedChannel(ch);
    setVideos([]);
    setTotalCount(0);
    setPage(1);
    setSearch('');
    setStatusFilter('all');
    setAiFilter('all');
    setMembersFilter('all');
  }

  function handleSearchChange(value) {
    setVideos([]);
    setTotalCount(0);
    setSearch(value);
    setPage(1);
  }

  function handleSortChange(newSort) {
    setVideos([]);
    setTotalCount(0);
    setSort(newSort);
    setPage(1);
  }

  function handleStatusFilterChange(value) {
    setVideos([]);
    setTotalCount(0);
    setStatusFilter(value);
    setPage(1);
  }

  function handleAiFilterChange(value) {
    setVideos([]);
    setTotalCount(0);
    setAiFilter(value);
    setPage(1);
  }

  function handleMembersFilterChange(value) {
    setVideos([]);
    setTotalCount(0);
    setMembersFilter(value);
    setPage(1);
  }

  const handleLoadMoreVideos = useCallback(() => {
    if (loading || loadingMore || videos.length >= totalCount) return;
    setPage(prev => prev + 1);
  }, [loading, loadingMore, videos.length, totalCount]);

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

  function addToast(text) {
    const id = Date.now();
    setToasts(prev => [...prev, { id, text }]);
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 5000);
  }

  function scrollToTop() {
    appContentRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

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

      <div className="app-content" ref={appContentRef}>
        {view === 'home' && (
          <>
	            <ChannelGrid
              channels={channels}
              totalVideos={allVideosCount}
              selectedChannel={selectedChannel}
              onSelect={handleSelectChannel}
	              onChannelsChanged={async () => {
	                await loadChannels();
	                await loadVideos({ targetPage: 1 });
	              }}
	            />

            <VideoTable
	              videos={videos}
	              totalCount={totalCount}
	              hasMore={videos.length < totalCount}
	              loadingMore={loadingMore}
	              onLoadMore={handleLoadMoreVideos}
              search={search}
              onSearchChange={handleSearchChange}
              sort={sort}
              onSortChange={handleSortChange}
              statusFilter={statusFilter}
              onStatusFilterChange={handleStatusFilterChange}
              aiFilter={aiFilter}
              onAiFilterChange={handleAiFilterChange}
              membersFilter={membersFilter}
              onMembersFilterChange={handleMembersFilterChange}
	              loading={loading}
	              onSelectVideo={video => setSelectedVideo({ ...video, channel: selectedChannel || video.channel_id })}
	              onVideosChanged={() => loadVideos({ targetPage: 1 })}
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
	              await loadVideos({ targetPage: 1 });
	            }}
          />
        )}
      </div>

      {toasts.length > 0 && (
        <div style={{ position: 'fixed', bottom: '4.75rem', right: '1.25rem', display: 'flex', flexDirection: 'column', gap: '0.4rem', zIndex: 2000 }}>
          {toasts.map(t => (
            <div key={t.id} style={{ background: 'rgba(76,175,80,0.9)', color: '#fff', padding: '0.55rem 0.9rem', borderRadius: '7px', fontSize: '0.88rem', fontWeight: 600, boxShadow: '0 2px 8px rgba(0,0,0,0.4)', cursor: 'pointer' }} onClick={() => setToasts(prev => prev.filter(x => x.id !== t.id))}>
              {t.text}
            </div>
          ))}
        </div>
      )}

      {showScrollTop && (
        <button
          type="button"
          className="scroll-top-button"
          onClick={scrollToTop}
          aria-label="Ugrás a lap tetejére"
          title="Ugrás a lap tetejére"
        >
          ↑
        </button>
      )}

      {selectedVideo && (
        <TranscriptModal
	          video={selectedVideo}
	          onClose={() => setSelectedVideo(null)}
	          onVideoUpdated={() => loadVideos({ targetPage: 1 })}
	        />
      )}
    </div>
  );
}
