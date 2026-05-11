import { useState, useCallback, useEffect } from 'react';
import { getStatus, stopProcessing, getWhisperStatus, startWhisperBatch, stopWhisper } from './fetcher.js';
import { keepIfSame } from './dataUtils.js';
import { POLL_INTERVAL_MS } from './constants.js';

export function useAppStatus(tRef) {
  const [fetcherStatus, setFetcherStatus] = useState(null);
  const [whisperStatus, setWhisperStatus] = useState(null);

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
    loadStatus();
    const id = setInterval(loadStatus, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [loadStatus]);

  const fetcherRunning = fetcherStatus && (
    fetcherStatus.fetch_active_size > 0
    || fetcherStatus.ai_active_size > 0
    || fetcherStatus.queue_size > 0
    || fetcherStatus.ai_queue_size > 0
    || Boolean(fetcherStatus.current_task?.type)
    || Boolean(fetcherStatus.current_ai_task?.type)
  );

  const whisperRunning = whisperStatus && (
    whisperStatus.queue_size > 0 || whisperStatus.batch_running
  );

  const handleStop = async () => {
    try {
      await stopProcessing();
      await loadStatus();
    } catch (e) {
      alert(tRef.current('msg.errGeneric', { error: e.message }));
    }
  };

  const handleWhisperStart = async () => {
    try {
      await startWhisperBatch();
      await loadStatus();
    } catch (e) {
      alert(tRef.current('msg.errWhisper', { error: e.message }));
    }
  };

  const handleWhisperStop = async () => {
    try {
      await stopWhisper();
      await loadStatus();
    } catch (e) {
      alert(tRef.current('msg.errWhisper', { error: e.message }));
    }
  };

  return {
    fetcherStatus, whisperStatus, fetcherRunning, whisperRunning,
    handleStop, handleWhisperStart, handleWhisperStop, loadStatus,
  };
}
