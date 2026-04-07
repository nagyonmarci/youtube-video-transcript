import { useState, useEffect, useCallback } from 'react';
import { getChannels, getVideos, getAllVideos } from './lib/directus.js';
import {
  stopProcessing, getStatus,
  getWhisperStatus, startWhisperBatch, stopWhisper, resumeWhisper,
} from './lib/fetcher.js';
import TopActions from './components/TopActions.jsx';
import ChannelGrid from './components/ChannelGrid.jsx';
import VideoTable from './components/VideoTable.jsx';
import TranscriptModal from './components/TranscriptModal.jsx';

export default function App() {
const [channels, setChannels] = useState([]);
  const [selectedChannel, setSelectedChannel] = useState(null);
  const [videos, setVideos] = useState([]);
  const [totalCount, setTotalCount] = useState(0);
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState('-uploaded_at');
  const [search, setSearch] = useState('');
  const [selectedVideo, setSelectedVideo] = useState(null);
  const [fetcherStatus, setFetcherStatus] = useState(null);
  const [whisperStatus, setWhisperStatus] = useState(null);
  const [loading, setLoading] = useState(false);

  const loadChannels = useCallback(async () => {
    try {
      const data = await getChannels();
      setChannels(data);
    } catch (e) {
      console.error('Failed to load channels', e);
    }
  }, []);

  const loadVideos = useCallback(async (showLoading = false) => {
    if (showLoading) setLoading(true);
    try {
      const opts = { sort, page, search };
      const result = selectedChannel
        ? await getVideos(selectedChannel.id, opts)
        : await getAllVideos(opts);
      setVideos(result.items);
      setTotalCount(result.total);
    } catch (e) {
      console.error('Failed to load videos', e);
    } finally {
      if (showLoading) setLoading(false);
    }
  }, [selectedChannel, page, sort, search]);

  const loadStatus = useCallback(async () => {
    try {
      const s = await getStatus();
      setFetcherStatus(s);
    } catch {
      setFetcherStatus(null);
    }
    try {
      const w = await getWhisperStatus();
      setWhisperStatus(w);
    } catch {
      setWhisperStatus(null);
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
    loadVideos(true);
    const interval = setInterval(() => loadVideos(false), 15000);
    return () => clearInterval(interval);
  }, [loadVideos]);

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

  return (
    <div className="app-layout">
      <header className="app-header">
        <span style={{ fontSize: '1.4rem' }}>▶</span>
        <h1 style={{ fontSize: '1.1rem', fontWeight: 700 }}>YouTube Transcript Downloader</h1>

        <div className="header-status">
          {/* Fetcher status */}
          {fetcherStatus && fetcherStatus.queue_size > 0 && (
            <span className="header-status-item">
              <span className="badge badge-processing">
                Feldolgozás: {fetcherStatus.queue_size} a sorban
                {fetcherStatus.current_task?.phase && ` • ${fetcherStatus.current_task.phase}`}
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
        <TopActions
          channels={channels}
          selectedChannel={selectedChannel}
          onChannelsChanged={loadChannels}
        />

        <ChannelGrid
          channels={channels}
          selectedChannel={selectedChannel}
          onSelect={handleSelectChannel}
          onChannelsChanged={loadChannels}
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
          onSelectVideo={setSelectedVideo}
          selectedChannel={selectedChannel}
        />
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
