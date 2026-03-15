import { useState, useEffect, useCallback } from 'react';
import { getChannels, getVideos, getAllVideos } from './lib/directus.js';
import { stopProcessing, getStatus } from './lib/fetcher.js';
import ChannelSidebar from './components/ChannelSidebar.jsx';
import VideoTable from './components/VideoTable.jsx';
import TranscriptModal from './components/TranscriptModal.jsx';

export default function App() {
  const [channels, setChannels] = useState([]);
  const [selectedChannel, setSelectedChannel] = useState(null); // null = all channels
  const [videos, setVideos] = useState([]);
  const [selectedVideo, setSelectedVideo] = useState(null);
  const [fetcherStatus, setFetcherStatus] = useState(null);
  const [loading, setLoading] = useState(false);

  const loadChannels = useCallback(async () => {
    try {
      const data = await getChannels();
      setChannels(data);
    } catch (e) {
      console.error('Failed to load channels', e);
    }
  }, []);

  const loadVideos = useCallback(async () => {
    setLoading(true);
    try {
      const data = selectedChannel
        ? await getVideos(selectedChannel.id)
        : await getAllVideos();
      setVideos(data);
    } catch (e) {
      console.error('Failed to load videos', e);
    } finally {
      setLoading(false);
    }
  }, [selectedChannel]);

  const loadStatus = useCallback(async () => {
    try {
      const s = await getStatus();
      setFetcherStatus(s);
    } catch {
      setFetcherStatus(null);
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
    loadVideos();
    const interval = setInterval(loadVideos, 15000);
    return () => clearInterval(interval);
  }, [loadVideos]);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  const handleStop = async () => {
    try {
      await stopProcessing();
      await loadStatus();
    } catch (e) {
      alert('Hiba: ' + e.message);
    }
  };

  return (
    <div className="app-layout">
      <header className="app-header">
        <span style={{ fontSize: '1.4rem' }}>▶</span>
        <h1 style={{ fontSize: '1.1rem', fontWeight: 700 }}>YouTube Transcript Downloader</h1>
        {fetcherStatus && fetcherStatus.queue_size > 0 && (
          <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span className="badge badge-processing">
              Feldolgozás: {fetcherStatus.queue_size} a sorban
              {fetcherStatus.current_task?.phase && ` • ${fetcherStatus.current_task.phase}`}
            </span>
            <button className="danger" onClick={handleStop} style={{ padding: '0.25rem 0.6rem' }}>
              Stop
            </button>
          </span>
        )}
      </header>

      <aside className="app-sidebar">
        <ChannelSidebar
          channels={channels}
          selectedChannel={selectedChannel}
          onSelect={(ch) => setSelectedChannel(ch)}
          onChannelsChanged={loadChannels}
          videos={videos}
        />
      </aside>

      <main className="app-main">
        <VideoTable
          videos={videos}
          loading={loading}
          onSelectVideo={setSelectedVideo}
          channels={channels}
          selectedChannel={selectedChannel}
        />
      </main>

      {selectedVideo && (
        <TranscriptModal
          video={selectedVideo}
          onClose={() => setSelectedVideo(null)}
        />
      )}
    </div>
  );
}
