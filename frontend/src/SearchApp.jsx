import { useState, useCallback, useEffect, useRef } from 'react';
import { getSearchResults } from './lib/directus.js';
import VideoTable from './components/VideoTable.jsx';
import TranscriptModal from './components/TranscriptModal.jsx';
import AppHeader from './components/AppHeader.jsx';
import { useAppStatus } from './lib/useAppStatus.js';
import { I18nProvider, useT } from './lib/i18n.jsx';
import { useTheme } from './lib/useTheme.js';

function SearchAppInner() {
  const { t, lang, setLanguage } = useT();
  const { theme, handleThemeToggle } = useTheme();
  const tRef = useRef(t);
  tRef.current = t;

  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [aiFilter, setAiFilter] = useState('all');
  const [membersFilter, setMembersFilter] = useState('hide');
  const [videos, setVideos] = useState([]);
  const [totalCount, setTotalCount] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [selectedVideo, setSelectedVideo] = useState(null);

  const {
    fetcherStatus, whisperStatus, fetcherRunning, whisperRunning,
    handleStop, handleWhisperStart, handleWhisperStop,
  } = useAppStatus(tRef);

  const loadResults = useCallback(async ({ showLoading = false, targetPage = page, append = false } = {}) => {
    if (!search.trim()) {
      setVideos([]);
      setTotalCount(0);
      return;
    }
    if (showLoading) setLoading(true);
    if (append) setLoadingMore(true);
    try {
      const result = await getSearchResults(search, { page: targetPage, statusFilter, aiFilter, membersFilter });
      setVideos(prev => {
        if (!append) return result.items;
        const seen = new Set(prev.map(v => v.id));
        return [...prev, ...result.items.filter(v => !seen.has(v.id))];
      });
      setTotalCount(result.total);
    } catch (e) {
      console.error('Failed to load search results', e);
    } finally {
      if (showLoading) setLoading(false);
      if (append) setLoadingMore(false);
    }
  }, [search, page, statusFilter, aiFilter, membersFilter]);

  useEffect(() => {
    loadResults({ showLoading: page === 1, targetPage: page, append: page > 1 });
  }, [loadResults, page]);

  function handleSearchChange(value) {
    setVideos([]);
    setTotalCount(0);
    setSearch(value);
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

  const handleLoadMore = useCallback(() => {
    if (loading || loadingMore || videos.length >= totalCount) return;
    setPage(prev => prev + 1);
  }, [loading, loadingMore, videos.length, totalCount]);

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

      <div className="app-content">
        <VideoTable
          videos={videos}
          totalCount={totalCount}
          hasMore={videos.length < totalCount}
          loadingMore={loadingMore}
          onLoadMore={handleLoadMore}
          search={search}
          onSearchChange={handleSearchChange}
          sort="-uploaded_at"
          onSortChange={() => {}}
          statusFilter={statusFilter}
          onStatusFilterChange={handleStatusFilterChange}
          aiFilter={aiFilter}
          onAiFilterChange={handleAiFilterChange}
          membersFilter={membersFilter}
          onMembersFilterChange={handleMembersFilterChange}
          loading={loading}
          onSelectVideo={video => setSelectedVideo({ ...video, channel: video.channel_id })}
          onVideosChanged={() => loadResults({ targetPage: 1 })}
          emptyMessage={search.trim() ? undefined : t('state.searchPrompt')}
          searchPlaceholder={t('placeholder.searchGlobal')}
        />
      </div>

      {selectedVideo && (
        <TranscriptModal
          video={selectedVideo}
          onClose={() => setSelectedVideo(null)}
          onVideoUpdated={() => loadResults({ targetPage: 1 })}
        />
      )}
    </div>
  );
}

export default function SearchApp() {
  return (
    <I18nProvider>
      <SearchAppInner />
    </I18nProvider>
  );
}
