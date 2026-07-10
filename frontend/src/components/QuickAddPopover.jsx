import { useEffect, useRef, useState } from 'react';
import { fetchChannels, fetchVideo } from '../lib/fetcher.js';
import { parseChannelFile } from '../lib/channelUtils.js';
import { useT } from '../lib/i18n.jsx';
import { useMessage } from '../lib/useMessage.js';

export default function QuickAddPopover() {
  const { t } = useT();
  const { msg, showMsg } = useMessage();
  const [open, setOpen] = useState(false);
  const [channelInput, setChannelInput] = useState('');
  const [videoInput, setVideoInput] = useState('');
  const [busy, setBusy] = useState(false);
  const fileInputRef = useRef();

  useEffect(() => {
    if (!open) return;
    const handler = () => setOpen(false);
    document.addEventListener('click', handler);
    return () => document.removeEventListener('click', handler);
  }, [open]);

  async function addChannels(urls) {
    if (!urls.length) return;
    setBusy(true);
    try {
      const result = await fetchChannels(urls);
      showMsg(t('msg.channelQueued', { count: result.count }));
    } catch (e) {
      showMsg(t('msg.errGeneric', { error: e.message }), true);
    } finally {
      setBusy(false);
    }
  }

  async function handleChannelSubmit(e) {
    e.preventDefault();
    const urls = channelInput.split('\n').map(l => l.trim()).filter(Boolean);
    await addChannels(urls);
    setChannelInput('');
  }

  async function handleVideoSubmit(e) {
    e.preventDefault();
    const url = videoInput.trim();
    if (!url) return;
    setBusy(true);
    try {
      await fetchVideo(url, null);
      showMsg(t('msg.videoQueued'));
      setVideoInput('');
    } catch (e) {
      showMsg(t('msg.errGeneric', { error: e.message }), true);
    } finally {
      setBusy(false);
    }
  }

  async function handleFileUpload(e) {
    const file = e.target.files[0];
    if (!file) return;
    const text = await file.text();
    const urls = parseChannelFile(text);
    e.target.value = '';
    await addChannels(urls);
  }

  return (
    <div className="quick-add-wrap">
      <button
        type="button"
        className="quick-add-trigger"
        title={t('btn.quickAdd')}
        aria-label={t('btn.quickAdd')}
        onClick={(e) => { e.stopPropagation(); setOpen(v => !v); }}
      >
        +
      </button>
      {open && (
        <div className="quick-add-popover" onClick={(e) => e.stopPropagation()}>
          <div className="card">
            <h3 className="card-title">{t('header.addChannel')}</h3>
            <form onSubmit={handleChannelSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
              <textarea
                rows={2}
                placeholder={t('placeholder.channelUrls')}
                value={channelInput}
                onChange={e => setChannelInput(e.target.value)}
                style={{ resize: 'vertical' }}
              />
              <div style={{ display: 'flex', gap: '0.4rem' }}>
                <button type="submit" className="primary" disabled={busy || !channelInput.trim()} style={{ flex: 1 }}>
                  {t('btn.add')}
                </button>
                <button type="button" onClick={() => fileInputRef.current.click()} disabled={busy}>
                  {t('btn.file')}
                </button>
              </div>
            </form>
            <input ref={fileInputRef} type="file" accept=".txt,.csv" style={{ display: 'none' }} onChange={handleFileUpload} />
          </div>

          <div className="card">
            <h3 className="card-title">{t('header.addVideo')}</h3>
            <form onSubmit={handleVideoSubmit} style={{ display: 'flex', gap: '0.4rem' }}>
              <input
                placeholder={t('placeholder.videoUrl')}
                value={videoInput}
                onChange={e => setVideoInput(e.target.value)}
              />
              <button type="submit" disabled={busy || !videoInput.trim()} style={{ whiteSpace: 'nowrap' }}>
                {t('btn.add')}
              </button>
            </form>
          </div>

          {msg && <div className={`status-msg ${msg.isError ? 'status-error' : 'status-success'}`}>{msg.text}</div>}
        </div>
      )}
    </div>
  );
}
