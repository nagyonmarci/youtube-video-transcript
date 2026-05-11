import { useState, useRef } from 'react';
import DailyUpdatesPage from './components/DailyUpdatesPage.jsx';
import TranscriptModal from './components/TranscriptModal.jsx';
import AppHeader from './components/AppHeader.jsx';
import { useAppStatus } from './lib/useAppStatus.js';
import { I18nProvider, useT } from './lib/i18n.jsx';
import { useTheme } from './lib/useTheme.js';
import { TOAST_TIMEOUT_MS } from './lib/constants.js';

function DailyAppInner() {
  const { t, lang, setLanguage } = useT();
  const { theme, handleThemeToggle } = useTheme();
  const [selectedVideo, setSelectedVideo] = useState(null);
  const [toasts, setToasts] = useState([]);
  const tRef = useRef(t);
  tRef.current = t;

  const {
    fetcherStatus, whisperStatus, fetcherRunning, whisperRunning,
    handleStop, handleWhisperStart, handleWhisperStop,
  } = useAppStatus(tRef);

  function addToast(text) {
    const id = Date.now();
    setToasts(prev => [...prev, { id, text }]);
    setTimeout(() => setToasts(prev => prev.filter(x => x.id !== id)), TOAST_TIMEOUT_MS);
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

      <div className="app-content">
        <DailyUpdatesPage
          onSelectVideo={video => setSelectedVideo({ ...video, channel: video.channel_id })}
        />
      </div>

      {toasts.length > 0 && (
        <div style={{ position: 'fixed', bottom: '4.75rem', right: '1.25rem', display: 'flex', flexDirection: 'column', gap: '0.4rem', zIndex: 2000 }}>
          {toasts.map(toast => (
            <div key={toast.id} style={{ background: 'rgba(76,175,80,0.9)', color: '#fff', padding: '0.55rem 0.9rem', borderRadius: '7px', fontSize: '0.88rem', fontWeight: 600, boxShadow: '0 2px 8px rgba(0,0,0,0.4)', cursor: 'pointer' }} onClick={() => setToasts(prev => prev.filter(x => x.id !== toast.id))}>
              {toast.text}
            </div>
          ))}
        </div>
      )}

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
