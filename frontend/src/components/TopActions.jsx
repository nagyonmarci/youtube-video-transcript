import { useEffect, useState, useRef } from 'react';
import { fetchChannels, fetchVideo, refreshDates, generateAiNotes, getSchedule, updateSchedule } from '../lib/fetcher.js';
import { getAllChannelVideos } from '../lib/directus.js';
import {
  channelToTxt, channelToMd, allChannelsToTxt, allChannelsToMd, allChannelsToObsidianMd,
  downloadFile, sanitizeFilename,
} from '../lib/export.js';
import { useT } from '../lib/i18n.jsx';
import { parseChannelFile } from '../lib/channelUtils.js';
import { cronToDailyTime, dailyTimeToCron } from '../lib/scheduleUtils.js';

export default function TopActions({ channels, selectedChannel, onChannelsChanged, showSchedule = false }) {
  const { t } = useT();
  const [channelInput, setChannelInput] = useState('');
  const [videoInput, setVideoInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [scheduleCron, setScheduleCron] = useState('0 7 * * *');
  const [scheduleTimezone, setScheduleTimezone] = useState('Europe/Budapest');
  const [scheduleTime, setScheduleTime] = useState('07:00');
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [advancedSchedule, setAdvancedSchedule] = useState(false);
  const fileInputRef = useRef();

  function showMsg(text, isError = false) {
    setMsg({ text, isError });
    setTimeout(() => setMsg(null), 4000);
  }

  async function addChannels(urls) {
    if (!urls.length) return;
    setBusy(true);
    try {
      const result = await fetchChannels(urls);
      showMsg(t('msg.channelQueued', { count: result.count }));
      onChannelsChanged();
    } catch (e) {
      showMsg(t('msg.errGeneric', { error: e.message }), true);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    let alive = true;
    getSchedule()
      .then(schedule => {
        if (!alive) return;
        const cron = schedule.cron || '0 7 * * *';
        setScheduleCron(cron);
        setScheduleTime(cronToDailyTime(cron));
        setScheduleTimezone(schedule.timezone || 'Europe/Budapest');
      })
      .catch(() => {});
    return () => { alive = false; };
  }, []);

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
      await fetchVideo(url, selectedChannel?.id ?? null);
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

  async function handleExportAll(fmt, timed = false) {
    try {
      const groups = await Promise.all(
        channels.map(async ch => ({
          channel: ch,
          videos: await getAllChannelVideos(ch.id),
        }))
      );
      const options = { timed };
      if (fmt === 'obsidian') {
        const content = allChannelsToObsidianMd(groups, { timed: true });
        downloadFile(content, 'youtube_tudasbazis_obsidian.md');
        return;
      }
      const content = fmt === 'md' ? allChannelsToMd(groups, options) : allChannelsToTxt(groups, options);
      downloadFile(content, `osszes_transkript${timed ? '_idovel' : ''}.${fmt}`);
    } catch (e) {
      showMsg(t('msg.errExport', { error: e.message }), true);
    }
  }

  async function handleScheduleSubmit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      const nextCron = advancedSchedule ? scheduleCron : dailyTimeToCron(scheduleTime);
      const schedule = await updateSchedule(nextCron, scheduleTimezone);
      setScheduleCron(schedule.cron);
      setScheduleTime(cronToDailyTime(schedule.cron));
      setScheduleTimezone(schedule.timezone);
      showMsg(t('msg.scheduleUpdated'));
      setScheduleOpen(false);
    } catch (e) {
      showMsg(t('msg.errSchedule', { error: e.message }), true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="top-actions">
      <div className="card top-action-card">
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

      <div className="card top-action-card">
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

      <div className="card top-action-card">
        <h3 className="card-title">{t('header.allExport')}</h3>
        <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
          <button onClick={() => handleExportAll('txt')} style={{ flex: 1 }}>{t('export.txt')}</button>
          <button onClick={() => handleExportAll('md')} style={{ flex: 1 }}>{t('export.md')}</button>
          <button onClick={() => handleExportAll('txt', true)} style={{ flex: 1 }}>{t('export.txtTimed')}</button>
          <button onClick={() => handleExportAll('md', true)} style={{ flex: 1 }}>{t('export.mdTimed')}</button>
          <button onClick={() => handleExportAll('obsidian')} style={{ flex: 1 }}>{t('export.obsidian')}</button>
        </div>
      </div>

      <div className="card top-action-card">
        <h3 className="card-title">{t('header.missingDates')}</h3>
        <button
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              const result = await refreshDates();
              showMsg(t('msg.dateRefreshQueued'));
            } catch (e) {
              showMsg(t('msg.errGeneric', { error: e.message }), true);
            } finally {
              setBusy(false);
            }
          }}
        >
          {t('btn.refresh')}
        </button>
      </div>

      <div className="card top-action-card">
        <h3 className="card-title">{t('header.aiNotes')}</h3>
        <button
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              const result = await generateAiNotes();
              showMsg(result?.existing
                ? t('msg.aiBatchRunning', { jobId: result.job_id?.slice(0, 8) })
                : t('msg.aiBatchQueued', { limit: result?.limit ?? '' })
              );
            } catch (e) {
              showMsg(t('msg.errAi', { error: e.message }), true);
            } finally {
              setBusy(false);
            }
          }}
        >
          {t('btn.generateMissing')}
        </button>
      </div>

      {showSchedule && (
        <div className="card top-action-card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.5rem' }}>
            <div>
              <h3 className="card-title" style={{ marginBottom: '0.15rem' }}>{t('header.autoRefresh')}</h3>
              <div style={{ fontSize: '0.78rem', color: '#aaa' }}>{scheduleCron} · {scheduleTimezone}</div>
            </div>
            <button type="button" onClick={() => setScheduleOpen(v => !v)} style={{ whiteSpace: 'nowrap' }}>
              {scheduleOpen ? t('btn.close') : t('btn.settings')}
            </button>
          </div>

          {scheduleOpen && (
            <form onSubmit={handleScheduleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', marginTop: '0.75rem' }}>
              <label style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem', fontSize: '0.78rem', color: '#aaa' }}>
                {t('label.dailyRefreshTime')}
                <input
                  type="time"
                  value={scheduleTime}
                  onChange={e => {
                    setScheduleTime(e.target.value);
                    if (!advancedSchedule) setScheduleCron(dailyTimeToCron(e.target.value));
                  }}
                />
              </label>
              <label style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem', fontSize: '0.78rem', color: '#aaa' }}>
                {t('label.timezone')}
                <select value={scheduleTimezone} onChange={e => setScheduleTimezone(e.target.value)}>
                  <option value="Europe/Budapest">Europe/Budapest</option>
                  <option value="UTC">UTC</option>
                  <option value="Europe/London">Europe/London</option>
                  <option value="Europe/Berlin">Europe/Berlin</option>
                  <option value="America/New_York">America/New_York</option>
                </select>
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.78rem', color: '#aaa' }}>
                <input
                  type="checkbox"
                  checked={advancedSchedule}
                  onChange={e => setAdvancedSchedule(e.target.checked)}
                />
                {t('label.advancedCron')}
              </label>
              {advancedSchedule && (
                <input
                  value={scheduleCron}
                  onChange={e => setScheduleCron(e.target.value)}
                  placeholder={t('placeholder.cronExpr')}
                  spellCheck={false}
                  style={{ fontFamily: 'monospace' }}
                />
              )}
              <button type="submit" disabled={busy || !scheduleTimezone.trim() || (advancedSchedule ? !scheduleCron.trim() : !scheduleTime)}>
                {t('btn.save')}
              </button>
            </form>
          )}
        </div>
      )}

      {msg && (
        <div className={`status-msg ${msg.isError ? 'status-error' : 'status-success'}`}>
          {msg.text}
        </div>
      )}
    </div>
  );
}
