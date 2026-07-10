import { useState, useEffect, useCallback, useRef } from 'react';
import { getChannels } from './lib/directus.ts';
import AdminDashboard from './components/AdminDashboard.tsx';
import AppHeader from './components/AppHeader.tsx';
import { useAppStatus } from './lib/useAppStatus.ts';
import { I18nProvider, useT } from './lib/i18n.tsx';
import { sameData, keepIfSame } from './lib/dataUtils.ts';
import { useTheme } from './lib/useTheme.ts';
import { POLL_INTERVAL_MS } from './lib/constants.ts';
import type { Channel } from './types.ts';

function AdminAppInner() {
  const { t, lang, setLanguage } = useT();
  const { theme, handleThemeToggle } = useTheme();
  const [channels, setChannels] = useState<Channel[]>([]);
  const [selectedChannel, setSelectedChannel] = useState<Channel | null>(null);
  const tRef = useRef(t);
  tRef.current = t;

  const {
    fetcherStatus, whisperStatus, fetcherRunning, whisperRunning,
    handleStop, handleWhisperStart, handleWhisperStop, loadStatus,
  } = useAppStatus(tRef);

  const loadChannels = useCallback(async () => {
    try {
      const data = await getChannels();
      setChannels(prev => keepIfSame(prev, data));
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
    loadChannels();
    const interval = setInterval(loadChannels, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [loadChannels]);

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
        <AdminDashboard
          channels={channels}
          selectedChannel={selectedChannel}
          fetcherStatus={fetcherStatus}
          whisperStatus={whisperStatus}
          onStatusChanged={loadStatus}
          onChannelsChanged={loadChannels}
        />
      </div>
    </div>
  );
}

export default function AdminApp() {
  return (
    <I18nProvider>
      <AdminAppInner />
    </I18nProvider>
  );
}
