import { useRef, useState, type FormEvent, type ChangeEvent } from 'react';
import { fetchChannels, fetchVideo } from './fetcher.ts';
import { parseChannelFile } from './channelUtils.ts';
import { useT } from './i18n.tsx';

interface UseQuickAddOptions {
  showMsg: (text: string, isError?: boolean) => void;
  busy: boolean;
  setBusy: (busy: boolean) => void;
  videoChannelId?: string | null;
  onChannelsAdded?: () => void;
}

export function useQuickAdd({ showMsg, busy, setBusy, videoChannelId = null, onChannelsAdded }: UseQuickAddOptions) {
  const { t } = useT();
  const [channelInput, setChannelInput] = useState('');
  const [videoInput, setVideoInput] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function addChannels(urls: string[]) {
    if (!urls.length) return;
    setBusy(true);
    try {
      const result = await fetchChannels(urls);
      showMsg(t('msg.channelQueued', { count: result.count }));
      onChannelsAdded?.();
    } catch (e) {
      showMsg(t('msg.errGeneric', { error: (e as Error).message }), true);
    } finally {
      setBusy(false);
    }
  }

  async function handleChannelSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const urls = channelInput.split('\n').map(l => l.trim()).filter(Boolean);
    await addChannels(urls);
    setChannelInput('');
  }

  async function handleVideoSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const url = videoInput.trim();
    if (!url) return;
    setBusy(true);
    try {
      await fetchVideo(url, videoChannelId);
      showMsg(t('msg.videoQueued'));
      setVideoInput('');
    } catch (e) {
      showMsg(t('msg.errGeneric', { error: (e as Error).message }), true);
    } finally {
      setBusy(false);
    }
  }

  async function handleFileUpload(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const text = await file.text();
    const urls = parseChannelFile(text);
    e.target.value = '';
    await addChannels(urls);
  }

  return {
    channelInput, setChannelInput,
    videoInput, setVideoInput,
    busy, fileInputRef,
    handleChannelSubmit, handleVideoSubmit, handleFileUpload,
  };
}
