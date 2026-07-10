import { useState, useEffect, useCallback, useRef } from 'react';
import { getChannels, getVideos, getAllVideos, getTotalVideoCount } from './lib/directus.js';
import ChannelGrid from './components/ChannelGrid.jsx';
import VideoTable from './components/VideoTable.jsx';
import TranscriptModal from './components/TranscriptModal.jsx';
import AppHeader from './components/AppHeader.jsx';
import { useAppStatus } from './lib/useAppStatus.js';
import { I18nProvider, useT } from './lib/i18n.jsx';
import { sameData, keepIfSame } from './lib/dataUtils.js';
import { useTheme } from './lib/useTheme.js';
import { useToasts } from './lib/useToasts.js';
import ToastStack from './components/ToastStack.jsx';
import { POLL_INTERVAL_MS } from './lib/constants.js';

function readUrlFilters() {
  const p = new URLSearchParams(window.location.search);
  return {
    search: p.get('q') || '',
    statusFilter: p.get('status') || 'all',
    aiFilter: p.get('ai') || 'all',
    membersFilter: p.get('members') || 'hide',
  };
}

function AppInner() {
  const { t, lang, setLanguage } = useT();
  const { theme, handleThemeToggle } = useTheme();
  const tRef = useRef(t);
  tRef.current = t;

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
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const { toasts, addToast, removeToast } = useToasts();
  const [showScrollTop, setShowScrollTop] = useState(false);
  const appContentRef = useRef(null);
  const prevFetcherRunning = useRef(false);
  const prevWhisperRunning = useRef(false);
  const selectedChannelId = selectedChannel?.id ?? null;

  const {
    fetcherStatus, whisperStatus, fetcherRunning, whisperRunning,
    handleStop, handleWhisperStart, handleWhisperStop, loadStatus,
  } = useAppStatus(tRef);

  useEffect(() => {
    if (prevFetcherRunning.current && !fetcherRunning) addToast(tRef.current('msg.processingDone'));
    prevFetcherRunning.current = !!fetcherRunning;
  }, [fetcherRunning]);

  useEffect(() => {
    if (prevWhisperRunning.current && !whisperRunning) addToast(tRef.current('msg.whisperDone'));
    prevWhisperRunning.current = !!whisperRunning;
  }, [whisperRunning]);

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
    if (membersFilter !== 'hide') p.set('members', membersFilter);
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

  useEffect(() => {
    loadChannels();
    const interval = setInterval(loadChannels, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [loadChannels]);

  useEffect(() => {
    loadVideos({ showLoading: page === 1, targetPage: page, append: page > 1 });
  }, [loadVideos, page]);

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

  function handleSelectChannel(ch) {
    setSelectedChannel(ch);
    setVideos([]);
    setTotalCount(0);
    setPage(1);
    setSearch('');
    setStatusFilter('all');
    setAiFilter('all');
    setMembersFilter('hide');
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

  function scrollToTop() {
    appContentRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  return (
    <div className="app-layout">
      <AppHeader
        fetcherStatus={fetcherStatus}
        whisperStatus={whisperStatus}
        fetcherRunning={fetcherRunning}
        whisperRunning={whisperRunning}
        handleStop={handleStop}
        handleWhisperStart={handleWhisperStart}
        handleWhisperStop={handleWhisperStop}
        theme={theme}
        onThemeToggle={handleThemeToggle}
        t={t}
        lang={lang}
        setLanguage={setLanguage}
      />

      <div className="app-content" ref={appContentRef}>
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
      </div>

      <ToastStack toasts={toasts} onDismiss={removeToast} />

      {showScrollTop && (
        <button
          type="button"
          className="scroll-top-button"
          onClick={scrollToTop}
          aria-label={t('btn.scrollToTop')}
          title={t('btn.scrollToTop')}
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

export default function App() {
  return (
    <I18nProvider>
      <AppInner />
    </I18nProvider>
  );
}
