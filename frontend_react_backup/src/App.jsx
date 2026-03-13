import { useState, useEffect, useCallback } from "react";
import { getChannels } from "./api/client";
import ChannelForm from "./components/ChannelForm";
import ChannelList from "./components/ChannelList";
import VideoList from "./components/VideoList";
import TranscriptModal from "./components/TranscriptModal";

export default function App() {
  const [channels, setChannels] = useState([]);
  const [selectedChannel, setSelectedChannel] = useState(null);
  const [selectedVideo, setSelectedVideo] = useState(null);

  const loadChannels = useCallback(() => {
    getChannels().then(setChannels);
  }, []);

  useEffect(() => {
    loadChannels();
    const interval = setInterval(loadChannels, 15000); // auto-refresh 15mp-ként
    return () => clearInterval(interval);
  }, [loadChannels]);

  return (
    <div className="app">
      <header>
        <h1>🎬 YouTube Transcript Manager</h1>
      </header>
      <main>
        <aside>
          <ChannelForm onAdded={loadChannels} />
          <ChannelList
            channels={channels}
            selected={selectedChannel}
            onSelect={setSelectedChannel}
            onDeleted={loadChannels}
          />
        </aside>
        <section>
          <VideoList
            channel={selectedChannel}
            onSelectVideo={setSelectedVideo}
          />
        </section>
      </main>
      <TranscriptModal
        videoId={selectedVideo}
        onClose={() => setSelectedVideo(null)}
      />
    </div>
  );
}
