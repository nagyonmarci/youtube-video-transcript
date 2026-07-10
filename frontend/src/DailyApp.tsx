import { useState, useRef } from 'react';
import DailyUpdatesPage from './components/DailyUpdatesPage.tsx';
import TranscriptModal from './components/TranscriptModal.tsx';
import AppHeader from './components/AppHeader.tsx';
import { useAppStatus } from './lib/useAppStatus.ts';
import { I18nProvider, useT } from './lib/i18n.tsx';
import { useTheme } from './lib/useTheme.ts';
import type { SelectedVideo } from './types.ts';

function DailyAppInner() {
  const { t, lang, setLanguage } = useT();
  const { theme, handleThemeToggle } = useTheme();
  const [selectedVideo, setSelectedVideo] = useState<SelectedVideo | null>(null);
  const tRef = useRef(t);
  tRef.current = t;

  const {
    fetcherStatus, whisperStatus, fetcherRunning, whisperRunning,
    handleStop, handleWhisperStart, handleWhisperStop,
  } = useAppStatus(tRef);

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
        <DailyUpdatesPage
          onSelectVideo={video => setSelectedVideo({ ...video, channel: video.channel_id })}
        />
      </div>


      {selectedVideo && (
        <TranscriptModal
          video={selectedVideo}
          onClose={() => setSelectedVideo(null)}
          onVideoUpdated={() => {}}
        />
      )}
    </div>
  );
}

export default function DailyApp() {
  return (
    <I18nProvider>
      <DailyAppInner />
    </I18nProvider>
  );
}
