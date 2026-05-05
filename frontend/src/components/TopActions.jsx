import { useEffect, useState, useRef } from 'react';
import { fetchChannels, fetchVideo, refreshDates, generateAiNotes, getSchedule, updateSchedule } from '../lib/fetcher.js';
import { getAllChannelVideos } from '../lib/directus.js';
import {
  channelToTxt, channelToMd, allChannelsToTxt, allChannelsToMd, allChannelsToObsidianMd,
  downloadFile, sanitizeFilename,
} from '../lib/export.js';

function parseChannelFile(text) {
  const lines = text.split(/\r?\n/).map(l => l.trim()).filter(l => l && !l.startsWith('#'));
  return lines.map(line => {
    if (line.includes(',')) {
      const parts = line.split(',').map(p => p.trim().replace(/^["']|["']$/g, ''));
      return parts.find(p => p.includes('youtube') || p.startsWith('@') || p.startsWith('UC')) || parts[0];
    }
    return line;
  }).filter(Boolean);
}

function cronToDailyTime(cron) {
  const parts = (cron || '').trim().split(/\s+/);
  if (parts.length !== 5 || parts[2] !== '*' || parts[3] !== '*' || parts[4] !== '*') {
    return '07:00';
  }
  const [minute, hour] = parts;
  if (!/^\d+$/.test(minute) || !/^\d+$/.test(hour)) return '07:00';
  return `${String(Math.min(23, Number(hour))).padStart(2, '0')}:${String(Math.min(59, Number(minute))).padStart(2, '0')}`;
}

function dailyTimeToCron(time) {
  const [hour = '7', minute = '0'] = (time || '07:00').split(':');
  return `${Number(minute)} ${Number(hour)} * * *`;
}

function scheduleLabel(cron, timezone) {
  const parts = (cron || '').trim().split(/\s+/);
  if (parts.length === 5 && parts[2] === '*' && parts[3] === '*' && parts[4] === '*') {
    return `Naponta ${cronToDailyTime(cron)} (${timezone || 'Europe/Budapest'})`;
  }
  return `${cron || 'nincs beállítva'} (${timezone || 'Europe/Budapest'})`;
}

export default function TopActions({ channels, selectedChannel, onChannelsChanged, showSchedule = false }) {
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
      showMsg(`${result.count} csatorna sorba állítva`);
      onChannelsChanged();
    } catch (e) {
      showMsg('Hiba: ' + e.message, true);
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
      showMsg('Videó sorba állítva');
      setVideoInput('');
    } catch (e) {
      showMsg('Hiba: ' + e.message, true);
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
      showMsg('Export hiba: ' + e.message, true);
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
      showMsg('Automatikus frissítés mentve');
      setScheduleOpen(false);
    } catch (e) {
      showMsg('Időzítés hiba: ' + e.message, true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="top-actions">
      {/* Add channel */}
      <div className="card top-action-card">
        <h3 className="card-title">Csatorna hozzáadása</h3>
        <form onSubmit={handleChannelSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
          <textarea
            rows={2}
            placeholder="URL-ek soronként (@handle, youtube.com/...)"
            value={channelInput}
            onChange={e => setChannelInput(e.target.value)}
            style={{ resize: 'vertical' }}
          />
          <div style={{ display: 'flex', gap: '0.4rem' }}>
            <button type="submit" className="primary" disabled={busy || !channelInput.trim()} style={{ flex: 1 }}>
              Hozzáad
            </button>
            <button type="button" onClick={() => fileInputRef.current.click()} disabled={busy}>
              Fájl
            </button>
          </div>
        </form>
        <input ref={fileInputRef} type="file" accept=".txt,.csv" style={{ display: 'none' }} onChange={handleFileUpload} />
      </div>

      {/* Add video */}
      <div className="card top-action-card">
        <h3 className="card-title">Videó hozzáadása</h3>
        <form onSubmit={handleVideoSubmit} style={{ display: 'flex', gap: '0.4rem' }}>
          <input
            placeholder="youtube.com/watch?v=..."
            value={videoInput}
            onChange={e => setVideoInput(e.target.value)}
          />
          <button type="submit" disabled={busy || !videoInput.trim()} style={{ whiteSpace: 'nowrap' }}>
            Hozzáad
          </button>
        </form>
      </div>

      {/* Export all */}
      <div className="card top-action-card">
        <h3 className="card-title">Összes export</h3>
        <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
          <button onClick={() => handleExportAll('txt')} style={{ flex: 1 }}>TXT</button>
          <button onClick={() => handleExportAll('md')} style={{ flex: 1 }}>MD</button>
          <button onClick={() => handleExportAll('txt', true)} style={{ flex: 1 }}>TXT idővel</button>
          <button onClick={() => handleExportAll('md', true)} style={{ flex: 1 }}>MD idővel</button>
          <button onClick={() => handleExportAll('obsidian')} style={{ flex: 1 }}>Obsidian</button>
        </div>
      </div>

      {/* Refresh dates */}
      <div className="card top-action-card">
        <h3 className="card-title">Hiányzó dátumok</h3>
        <button
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await refreshDates();
              showMsg('Dátum frissítés sorba állítva');
            } catch (e) {
              showMsg('Hiba: ' + e.message, true);
            } finally {
              setBusy(false);
            }
          }}
        >
          Frissítés
        </button>
      </div>

      {/* AI notes */}
      <div className="card top-action-card">
        <h3 className="card-title">AI jegyzetek</h3>
        <button
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await generateAiNotes(10);
              showMsg('AI jegyzet generálás sorba állítva');
            } catch (e) {
              showMsg('AI jegyzet hiba: ' + e.message, true);
            } finally {
              setBusy(false);
            }
          }}
        >
          Hiányzók generálása
        </button>
      </div>

      {showSchedule && (
        <div className="card top-action-card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.5rem' }}>
            <div>
              <h3 className="card-title" style={{ marginBottom: '0.15rem' }}>Automatikus frissítés</h3>
              <div style={{ fontSize: '0.78rem', color: '#aaa' }}>{scheduleLabel(scheduleCron, scheduleTimezone)}</div>
            </div>
            <button type="button" onClick={() => setScheduleOpen(v => !v)} style={{ whiteSpace: 'nowrap' }}>
              {scheduleOpen ? 'Bezár' : 'Beállítás'}
            </button>
          </div>

          {scheduleOpen && (
            <form onSubmit={handleScheduleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', marginTop: '0.75rem' }}>
              <label style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem', fontSize: '0.78rem', color: '#aaa' }}>
                Napi frissítés ideje
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
                Időzóna
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
                Haladó cron
              </label>
              {advancedSchedule && (
                <input
                  value={scheduleCron}
                  onChange={e => setScheduleCron(e.target.value)}
                  placeholder="0 7 * * *"
                  spellCheck={false}
                  style={{ fontFamily: 'monospace' }}
                />
              )}
              <button type="submit" disabled={busy || !scheduleTimezone.trim() || (advancedSchedule ? !scheduleCron.trim() : !scheduleTime)}>
                Mentés
              </button>
            </form>
          )}
        </div>
      )}

      {/* Status message */}
      {msg && (
        <div className={`status-msg ${msg.isError ? 'status-error' : 'status-success'}`}>
          {msg.text}
        </div>
      )}
    </div>
  );
}
