import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { getAdminStats, getChannelCoverage, getMonthlyVideoCounts } from '../lib/directus.ts';
import {
  deleteJob,
  generateAiNotes,
  getAppSettings,
  getJobs,
  getResources,
  getSchedule,
  openResourceStream,
  moveJob,
  pauseJob,
  refreshDates,
  refreshThumbnails,
  resumeJob,
  startJob,
  resumeProcessing,
  stopProcessing,
  stopWhisper,
  updateAppSettings,
  updateSchedule,
} from '../lib/fetcher.ts';
import ChannelAdminPanel from './ChannelAdminPanel.tsx';
import TopActions from './TopActions.tsx';
import SettingsForm from './SettingsForm.tsx';
import StatisticsPanel from './StatisticsPanel.tsx';
import CollapsibleSection from './CollapsibleSection.tsx';
import { useT } from '../lib/i18n.tsx';
import { keepIfSame } from '../lib/dataUtils.ts';
import { cronToDailyTime, dailyTimeToCron } from '../lib/scheduleUtils.ts';
import { useMessage } from '../lib/useMessage.ts';
import { POLL_INTERVAL_MS, DEFAULT_CRON, DEFAULT_CRON_TIME, DEFAULT_TIMEZONE } from '../lib/constants.ts';
import { formatJobTime, formatDurationWords } from '../lib/formatUtils.ts';
import type { Channel, Job, AppSettings, AdminStats, ChannelCoverageMaps, MonthlyVideoCount, FetcherStatus, WhisperStatus, CurrentTask, QueueCounts, JobMetrics, OllamaStatus } from '../types.ts';

function formatProgress(current: number | null | undefined, total: number | null | undefined): string {
  const cur = Number(current || 0);
  const max = Number(total || 0);
  if (!cur || !max) return '';
  return `${cur}/${max} (${Math.round((cur / max) * 100)}%)`;
}

function normalizeSettings(settings: Partial<AppSettings> = {}): AppSettings {
  return {
    ollama_base_url: settings.ollama_base_url || 'http://host.docker.internal:11434',
    ollama_chat_model: settings.ollama_chat_model || 'gemma4:31b-mlx-bf16',
    ollama_timeout: Number(settings.ollama_timeout ?? 600),
    ai_notes_max_chars: Number(settings.ai_notes_max_chars ?? 45000),
    ai_notes_auto: Boolean(settings.ai_notes_auto),
    ai_notes_batch_limit: Number(settings.ai_notes_batch_limit ?? 10),
    ai_notes_max_batch_limit: Number(settings.ai_notes_max_batch_limit ?? 20000),
    ai_notes_year_backfill_enabled: Boolean(settings.ai_notes_year_backfill_enabled),
    ai_notes_year_backfill_year: Number(settings.ai_notes_year_backfill_year ?? new Date().getFullYear()),
    ai_notes_year_backfill_batch_limit: Number(settings.ai_notes_year_backfill_batch_limit ?? 50),
    ai_notes_year_backfill_target_active: Number(settings.ai_notes_year_backfill_target_active ?? 100),
    ai_notes_year_backfill_interval_seconds: Number(settings.ai_notes_year_backfill_interval_seconds ?? 300),
    ai_notes_year_backfill_idle_seconds: Number(settings.ai_notes_year_backfill_idle_seconds ?? 60),
    ai_notes_worker_enabled: settings.ai_notes_worker_enabled ?? true,
    ai_notes_job_cooldown_seconds: Number(settings.ai_notes_job_cooldown_seconds ?? 0),
    ai_notes_quick_enabled: settings.ai_notes_quick_enabled ?? true,
    ollama_quick_model: settings.ollama_quick_model || 'qwen3:4b',
    ollama_quick_timeout: Number(settings.ollama_quick_timeout ?? 120),
    ollama_num_ctx: Number(settings.ollama_num_ctx ?? 32768),
    ollama_quick_num_ctx: Number(settings.ollama_quick_num_ctx ?? 4096),
    ollama_temperature: Number(settings.ollama_temperature ?? 0.1),
    ollama_num_predict: Number(settings.ollama_num_predict ?? 8192),
    ai_provider: settings.ai_provider || 'ollama',
    ai_cloud_model: settings.ai_cloud_model || 'claude-opus-4-7',
    anthropic_api_key: settings.anthropic_api_key || '',
    openai_api_key: settings.openai_api_key || '',
    openai_base_url: settings.openai_base_url || 'https://api.openai.com/v1',
    ai_night_window_enabled: Boolean(settings.ai_night_window_enabled),
    ai_night_window_start_hour: Number(settings.ai_night_window_start_hour ?? 17),
    ai_night_window_stop_hour: Number(settings.ai_night_window_stop_hour ?? 7),
    channel_job_video_cap: Number(settings.channel_job_video_cap ?? 100),
    channel_backlog_window_enabled: Boolean(settings.channel_backlog_window_enabled ?? true),
    channel_backlog_start_hour: Number(settings.channel_backlog_start_hour ?? 19),
    channel_backlog_stop_hour: Number(settings.channel_backlog_stop_hour ?? 7),
  };
}

const SECTION_IDS = ['statistics', 'processing', 'schedule', 'setup', 'quickActions', 'channelAdmin'];
const SECTION_STORAGE_KEY = 'yt_admin_sections';

interface SectionPrefs {
  order: string[];
  collapsed: Record<string, boolean>;
}

function loadSectionPrefs(): SectionPrefs {
  let raw = null;
  try { raw = JSON.parse(localStorage.getItem(SECTION_STORAGE_KEY) || 'null'); } catch { raw = null; }
  const savedOrder: string[] = Array.isArray(raw?.order) ? raw.order.filter((id: string) => SECTION_IDS.includes(id)) : [];
  const order = [...savedOrder, ...SECTION_IDS.filter(id => !savedOrder.includes(id))];
  const collapsed = { ...Object.fromEntries(SECTION_IDS.map(id => [id, true])), ...(raw?.collapsed || {}) };
  return { order, collapsed };
}

function saveSectionPrefs(prefs: SectionPrefs): void {
  try { localStorage.setItem(SECTION_STORAGE_KEY, JSON.stringify(prefs)); } catch {}
}

function formatBytes(value: number | null | undefined): string {
  const bytes = Number(value || 0);
  if (!bytes) return '-';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / (1024 ** index)).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

interface AiStatusResult {
  tone: string;
  title: string;
  detail: string;
}

interface AiStatusArgs {
  appSettings: AppSettings;
  fetcherStatus: FetcherStatus | null;
  jobs: Job[];
  missingAiNotes: number;
  t: (key: string, vars?: Record<string, unknown>) => string;
}

function getAiStatus({ appSettings, fetcherStatus, jobs, missingAiNotes, t }: AiStatusArgs): AiStatusResult {
  const aiQueue: Partial<QueueCounts> = fetcherStatus?.queues?.ai || {};
  const aiQueueSize = Number(aiQueue.queued ?? fetcherStatus?.ai_queue_size ?? 0);
  const actualRunning = Number(aiQueue.running ?? 0);
  const workerConcurrency = Number(fetcherStatus?.workers?.ai_concurrency ?? fetcherStatus?.resources?.ai_worker_concurrency ?? 0);
  const currentAiTask = fetcherStatus?.current_ai_task;
  const aiJobs = jobs.filter(job => job.queue === 'ai' && !['done', 'cancelled'].includes(job.status));
  const runningJobs = actualRunning || aiJobs.filter(job => job.status === 'running').length;
  const queuedJobs = aiQueueSize || aiJobs.filter(job => job.status === 'queued').length;
  const pausedJobs = aiJobs.filter(job => job.status === 'paused').length;
  const isActive = Boolean(currentAiTask?.type) || runningJobs > 0;
  const missingCount = Number(missingAiNotes || 0);

  if (isActive) {
    return {
      tone: 'running',
      title: t('aiStatus.runningTitle'),
      detail: t('aiStatus.runningDetail', {
        queued: queuedJobs,
        running: runningJobs,
        workers: workerConcurrency || 1,
        task: currentAiTask?.phase || currentAiTask?.video || currentAiTask?.video_id || t('aiStatus.currentTaskFallback'),
      }),
    };
  }

  if (!appSettings.ai_notes_worker_enabled) {
    return {
      tone: 'paused',
      title: t('aiStatus.workerOffTitle'),
      detail: t('aiStatus.workerOffDetail', { count: missingCount }),
    };
  }

  if (pausedJobs > 0) {
    return {
      tone: 'paused',
      title: t('aiStatus.pausedTitle'),
      detail: t('aiStatus.pausedDetail', { count: pausedJobs }),
    };
  }

  if (queuedJobs > 0) {
    return {
      tone: 'queued',
      title: t('aiStatus.queuedTitle'),
      detail: t('aiStatus.queuedDetail', { count: queuedJobs }),
    };
  }

  if (missingCount <= 0) {
    return {
      tone: 'idle',
      title: t('aiStatus.completeTitle'),
      detail: t('aiStatus.completeDetail'),
    };
  }

  if (!appSettings.ai_notes_auto && !appSettings.ai_notes_year_backfill_enabled) {
    return {
      tone: 'manual',
      title: t('aiStatus.manualTitle'),
      detail: t('aiStatus.manualDetail', { count: missingCount }),
    };
  }

  if (appSettings.ai_notes_year_backfill_enabled) {
    return {
      tone: 'waiting',
      title: t('aiStatus.backfillTitle'),
      detail: t('aiStatus.backfillDetail', {
        count: missingCount,
        interval: appSettings.ai_notes_year_backfill_interval_seconds,
      }),
    };
  }

  return {
    tone: 'waiting',
    title: t('aiStatus.autoTitle'),
    detail: t('aiStatus.autoDetail', { count: missingCount }),
  };
}

interface StatusLineProps {
  title: string;
  queueSize?: number;
  queueStats?: Partial<QueueCounts>;
  workerCount?: number;
  current?: CurrentTask;
  stopped?: boolean;
  onStop?: () => void;
  onStart?: () => void;
}

function StatusLine({ title, queueSize, queueStats, workerCount, current, stopped, onStop, onStart }: StatusLineProps) {
  const { t } = useT();
  const queued = Number(queueStats?.queued ?? queueSize ?? 0);
  const running = Number(queueStats?.running ?? (current?.type ? 1 : 0));
  const paused = Number(queueStats?.paused ?? 0);
  const active = queued > 0 || running > 0 || Boolean(current?.type);
  const progressText = formatProgress(current?.progress_current, current?.progress_total);
  const runtimeText = formatDurationWords(current?.duration_seconds);
  const badgeClass = stopped ? 'badge-paused' : active ? 'badge-processing' : 'badge-done';
  const badgeLabel = stopped ? t('status.stopped') : active ? t('status.running') : t('status.empty');
  return (
    <div className="process-line">
      <div>
        <h4>{title}</h4>
        <p>
          {active ? (
            <>
              <span>{t('label.queueBreakdown', { queued, running, paused })}</span>
              {workerCount !== undefined && <span> · {t('label.workerSlots', { count: workerCount })}</span>}
              {current?.phase && <span> · {current.phase}</span>}
              {current?.video && <span> · {current.video}</span>}
              {current?.video_id && !current?.video && <span> · {current.video_id}</span>}
              {progressText && <span> · {progressText}</span>}
              {runtimeText && <span> · {t('label.runningFor', { duration: runtimeText })}</span>}
            </>
          ) : (
            <span>{t('state.noRunning')}</span>
          )}
        </p>
        {progressText && (
          <progress
            className="job-progress"
            value={Number(current?.progress_current || 0)}
            max={Number(current?.progress_total || 1)}
          />
        )}
      </div>
      <div className="process-actions">
        <span className={`badge ${badgeClass}`}>{badgeLabel}</span>
        {(active || stopped) && onStop && <button className="danger" onClick={onStop}>{t('btn.stop')}</button>}
        {onStart && <button onClick={onStart}>{t('btn.start')}</button>}
      </div>
    </div>
  );
}

function jobRuntimeSeconds(job: Job): number {
  if (job.duration_seconds) return Number(job.duration_seconds);
  if (!job.started_at) return 0;
  const end = job.finished_at ? new Date(job.finished_at) : new Date();
  return Math.max(0, Math.round((end.getTime() - new Date(job.started_at).getTime()) / 1000));
}

function formatMetricSeconds(value: number | null | undefined): string {
  if (value === null || value === undefined) return '-';
  const number = Number(value);
  if (!Number.isFinite(number)) return '-';
  return `${number.toFixed(number >= 10 ? 1 : 2)}s`;
}

function aiBottleneck(metrics: JobMetrics | null | undefined): { phase: string; seconds: number } | '' {
  if (!metrics) return '';
  const phases = ([
    ['load', Number(metrics.ollama_load_seconds || 0)],
    ['firstToken', Number(metrics.first_token_seconds || 0)],
    ['prompt', Number(metrics.prompt_eval_seconds || 0)],
    ['generate', Number(metrics.eval_seconds || 0)],
    ['parse', Number(metrics.json_parse_seconds || 0)],
  ] as [string, number][]).filter(([, value]) => value > 0);
  if (!phases.length) return '';
  const [phase, seconds] = phases.sort((a, b) => b[1] - a[1])[0];
  return { phase, seconds };
}

interface JobQueuePanelProps {
  jobs: Job[];
  onAction: (action: () => Promise<unknown>) => Promise<void>;
  busy: boolean;
}

function JobQueuePanel({ jobs, onAction, busy }: JobQueuePanelProps) {
  const { t } = useT();
  const [showCompleted, setShowCompleted] = useState(false);

  const JOB_STATUS_LABELS: Record<string, string> = {
    queued: t('status.queued'),
    running: t('status.running'),
    paused: t('status.paused'),
    done: t('status.done'),
    error: t('status.error'),
    cancelled: t('status.cancelled'),
  };

  const activeJobs = jobs.filter(job => job.status !== 'done' && job.status !== 'cancelled');
  const completedJobs = jobs.filter(job => job.status === 'done' || job.status === 'cancelled');
  const visibleJobs = showCompleted ? jobs.slice(0, 100) : activeJobs.slice(0, 80);
  return (
    <>
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.4rem', alignItems: 'center' }}>
        <span style={{ fontSize: '0.78rem', color: 'var(--text2)' }}>{t('label.activeJobs', { count: activeJobs.length })}</span>
        {completedJobs.length > 0 && (
          <button style={{ fontSize: '0.75rem', padding: '0.15rem 0.45rem' }} onClick={() => setShowCompleted(v => !v)}>
            {showCompleted ? t('label.activeOnly') : t('label.plusCompleted', { count: completedJobs.length })}
          </button>
        )}
      </div>
      <div className="job-table-wrap">
        <table className="job-table">
          <thead>
            <tr>
              <th>{t('label.queue')}</th>
              <th>{t('label.task')}</th>
              <th>{t('label.status')}</th>
              <th>{t('label.createdAt')}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {visibleJobs.map(job => {
              const running = job.status === 'running';
              const paused = job.status === 'paused';
              const reorderable = ['queued', 'paused'].includes(job.status);
              const progressText = formatProgress(job.progress_current, job.progress_total);
              const runtimeText = formatDurationWords(jobRuntimeSeconds(job));
              const bottleneck = job.queue === 'ai' ? aiBottleneck(job.metrics) : null;
              return (
                <tr key={job.id}>
                  <td>
                    <span className={`badge ${job.queue === 'ai' ? 'badge-whisper' : 'badge-processing'}`}>
                      {job.queue}
                    </span>
                  </td>
                  <td>
                    <div className="job-label">{job.label || job.type}</div>
                    {runtimeText && (
                      <div className="job-progress-text">
                        {running ? t('label.runningFor', { duration: runtimeText }) : t('label.duration', { duration: runtimeText })}
                      </div>
                    )}
                    {bottleneck && (
                      <div className="job-progress-text">
                        {t('label.aiBottleneck', {
                          phase: t(`aiMetric.${bottleneck.phase}`),
                          duration: formatMetricSeconds(bottleneck.seconds),
                        })}
                      </div>
                    )}
                    {job.queue === 'ai' && job.metrics && (
                      <div className="job-progress-text">
                        {t('label.aiMetrics', {
                          first: formatMetricSeconds(job.metrics.first_token_seconds),
                          prompt: formatMetricSeconds(job.metrics.prompt_eval_seconds),
                          generate: formatMetricSeconds(job.metrics.eval_seconds),
                          rate: job.metrics.eval_tokens_per_second ? `${job.metrics.eval_tokens_per_second} tok/s` : '-',
                        })}
                      </div>
                    )}
                    {progressText && <div className="job-progress-text">{progressText}</div>}
                    {progressText && (
                      <progress
                        className="job-progress"
                        value={Number(job.progress_current || 0)}
                        max={Number(job.progress_total || 1)}
                      />
                    )}
                    {job.error_message && <div className="job-error">{job.error_message}</div>}
                  </td>
                  <td>
                    <span className={`badge badge-${job.status}`}>
                      {JOB_STATUS_LABELS[job.status] || job.status}
                    </span>
                    {Number(job.attempts || 0) > 0 && (
                      <div className="job-progress-text">
                        {t('label.attempts', { current: job.attempts, max: job.max_attempts || 3 })}
                      </div>
                    )}
                  </td>
                  <td>{formatJobTime(job.created_at)}</td>
                  <td>
                    <div className="job-actions">
                      <button disabled={busy || !reorderable} onClick={() => onAction(() => moveJob(job.id, 'up'))}>{t('btn.up')}</button>
                      <button disabled={busy || !reorderable} onClick={() => onAction(() => moveJob(job.id, 'down'))}>{t('btn.down')}</button>
                      {paused ? (
                        <button disabled={busy} onClick={() => onAction(() => resumeJob(job.id))}>{t('btn.resume')}</button>
                      ) : (
                        <button disabled={busy || running || ['done', 'cancelled'].includes(job.status)} onClick={() => onAction(() => pauseJob(job.id))}>{t('btn.pause')}</button>
                      )}
                      <button disabled={busy || running} onClick={() => onAction(() => startJob(job.id))}>{t('btn.start')}</button>
                      <button className="danger" disabled={busy} onClick={() => onAction(() => deleteJob(job.id))}>{t('btn.delete')}</button>
                    </div>
                  </td>
                </tr>
              );
            })}
            {visibleJobs.length === 0 && (
              <tr>
                <td colSpan={5} className="admin-empty">{t('state.noJobs')}</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

interface AdminDashboardProps {
  channels: Channel[];
  selectedChannel: Channel | null;
  fetcherStatus: FetcherStatus | null;
  whisperStatus: WhisperStatus | null;
  onChannelsChanged: () => Promise<void> | void;
  onStatusChanged?: () => Promise<void> | void;
}

export default function AdminDashboard({
  channels,
  selectedChannel,
  fetcherStatus,
  whisperStatus,
  onChannelsChanged,
  onStatusChanged,
}: AdminDashboardProps) {
  const { t } = useT();
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [coverage, setCoverage] = useState<ChannelCoverageMaps | null>(null);
  const [monthlyData, setMonthlyData] = useState<MonthlyVideoCount[]>([]);
  const [scheduleCron, setScheduleCron] = useState(DEFAULT_CRON);
  const [scheduleTime, setScheduleTime] = useState(DEFAULT_CRON_TIME);
  const [scheduleTimezone, setScheduleTimezone] = useState(DEFAULT_TIMEZONE);
  const [appSettings, setAppSettings] = useState(() => normalizeSettings());
  const [settingsDraft, setSettingsDraft] = useState(() => normalizeSettings());
  const [settingsDirty, setSettingsDirty] = useState(false);
  const settingsDirtyRef = useRef(false);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [resourceSnapshot, setResourceSnapshot] = useState<FetcherStatus['resources'] | null>(null);
  const [busy, setBusy] = useState(false);
  const [sectionPrefs, setSectionPrefs] = useState(loadSectionPrefs);
  const [draggedSectionId, setDraggedSectionId] = useState<string | null>(null);
  const [dragOverSectionId, setDragOverSectionId] = useState<string | null>(null);
  const { msg, showMsg } = useMessage();

  useEffect(() => { saveSectionPrefs(sectionPrefs); }, [sectionPrefs]);

  function toggleSection(id: string) {
    setSectionPrefs(prev => ({ ...prev, collapsed: { ...prev.collapsed, [id]: !prev.collapsed[id] } }));
  }
  function handleSectionDragStart(id: string) { setDraggedSectionId(id); }
  function handleSectionDragEnd() { setDraggedSectionId(null); setDragOverSectionId(null); }
  function handleSectionDragOver(id: string) { setDragOverSectionId(id); }
  function handleSectionDragLeave() { setDragOverSectionId(null); }
  function handleSectionDrop(targetId: string) {
    const draggedId = draggedSectionId;
    setDraggedSectionId(null);
    setDragOverSectionId(null);
    if (!draggedId || draggedId === targetId) return;
    setSectionPrefs(prev => {
      const next = prev.order.filter(id => id !== draggedId);
      next.splice(next.indexOf(targetId), 0, draggedId);
      return { ...prev, order: next };
    });
  }

  async function loadAdminData() {
    try {
      const [nextStats, schedule, jobData, cov, monthly, settings] = await Promise.all([
        getAdminStats(),
        getSchedule(),
        getJobs(),
        getChannelCoverage(),
        getMonthlyVideoCounts(),
        getAppSettings(),
      ]);
      const nextCron = schedule.cron || DEFAULT_CRON;
      const nextTime = cronToDailyTime(nextCron);
      const nextTimezone = schedule.timezone || DEFAULT_TIMEZONE;
      setStats(prev => keepIfSame(prev, nextStats));
      setJobs(prev => keepIfSame(prev, jobData.jobs || []));
      setCoverage(cov);
      setMonthlyData(monthly);
      setScheduleCron(prev => (prev === nextCron ? prev : nextCron));
      setScheduleTime(prev => (prev === nextTime ? prev : nextTime));
      setScheduleTimezone(prev => (prev === nextTimezone ? prev : nextTimezone));
      const normalizedSettings = normalizeSettings(settings);
      setAppSettings(normalizedSettings);
      if (!settingsDirtyRef.current) setSettingsDraft(normalizedSettings);
    } catch (e) {
      showMsg(t('msg.errAdmin', { error: (e as Error).message }), true);
    }
  }

  useEffect(() => {
    loadAdminData();
    const interval = setInterval(loadAdminData, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    let alive = true;
    let fallbackInterval: ReturnType<typeof setInterval> | null = null;
    let stream: EventSource | null = null;

    async function loadResources() {
      try {
        const resources = await getResources();
        if (alive) setResourceSnapshot(resources);
      } catch {
        if (alive) setResourceSnapshot(prev => prev);
      }
    }

    function startFallbackPolling() {
      if (fallbackInterval) return;
      loadResources();
      fallbackInterval = setInterval(loadResources, 2000);
    }

    if (typeof EventSource === 'undefined') {
      startFallbackPolling();
    } else {
      stream = openResourceStream();
      stream.onmessage = event => {
        try {
          const resources = JSON.parse(event.data);
          if (alive) setResourceSnapshot(resources);
        } catch {
          if (alive) setResourceSnapshot(prev => prev);
        }
      };
      stream.onerror = () => {
        stream?.close();
        stream = null;
        startFallbackPolling();
      };
    }

    return () => {
      alive = false;
      stream?.close();
      if (fallbackInterval) clearInterval(fallbackInterval);
    };
  }, []);

  async function runAction<T>(action: () => Promise<T>, successText: string | ((result: T) => string)) {
    setBusy(true);
    try {
      const result = await action();
      showMsg(typeof successText === 'function' ? successText(result) : successText);
      await Promise.all([loadAdminData(), onStatusChanged?.()]);
    } catch (e) {
      showMsg(t('msg.errGeneric', { error: (e as Error).message }), true);
    } finally {
      setBusy(false);
    }
  }

  async function runJobAction(action: () => Promise<unknown>) {
    await runAction(action, t('msg.queueRefreshed'));
  }

  async function saveSchedule(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    await runAction(
      () => updateSchedule(dailyTimeToCron(scheduleTime), scheduleTimezone),
      t('msg.scheduleUpdated')
    );
  }

  function updateSettingsDraft(field: keyof AppSettings, value: string | number | boolean) {
    settingsDirtyRef.current = true;
    setSettingsDirty(true);
    setSettingsDraft(prev => ({ ...prev, [field]: value }));
  }

  async function saveAppSettings(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    await runAction(
      () => updateAppSettings(settingsDraft),
      t('msg.settingsUpdated')
    );
    settingsDirtyRef.current = false;
    setSettingsDirty(false);
  }

  const channelCount = channels.length;
  const totalChannelVideos = channels.reduce((sum, ch) => sum + (ch.video_count || 0), 0);
  const displayedTotalVideos = stats?.totalVideos ?? totalChannelVideos;
  const missingAiNotes = Number(stats?.missingAiNotes || 0);
  const aiStatus = getAiStatus({ appSettings, fetcherStatus, jobs, missingAiNotes, t });
  const aiBatchLimit = Number(appSettings.ai_notes_batch_limit || 10);
  const aiCanStart = missingAiNotes > 0;
  const resourceStatus: Partial<FetcherStatus['resources']> = resourceSnapshot || fetcherStatus?.resources || {};
  const ollamaStatus: Partial<OllamaStatus> = resourceStatus.ollama || {};
  const ollamaModels = ollamaStatus.models || [];
  const primaryOllamaModel = ollamaModels[0];
  const processorPercent = primaryOllamaModel?.processor_percent;
  const sampledAt = ollamaStatus.sampled_at ? new Date(ollamaStatus.sampled_at).toLocaleTimeString('hu-HU') : '-';
  const fetchQueue: Partial<QueueCounts> = fetcherStatus?.queues?.fetch || {};
  const quickQueue: Partial<QueueCounts> = fetcherStatus?.queues?.quick || {};
  const aiQueue: Partial<QueueCounts> = fetcherStatus?.queues?.ai || resourceStatus.ai_queue || {};
  const fetchWorkers = fetcherStatus?.workers?.fetch_concurrency;
  const quickWorkers = fetcherStatus?.workers?.quick_concurrency;
  const aiWorkers = fetcherStatus?.workers?.ai_concurrency ?? resourceStatus.ai_worker_concurrency;
  const stoppedQueues: Partial<{ fetch: boolean; quick: boolean; ai: boolean }> = fetcherStatus?.stopped_queues || {};

  function getSectionConfig(id: string): { title?: ReactNode; subtitle?: ReactNode; headerExtra?: ReactNode; body?: ReactNode } {
    switch (id) {
      case 'statistics':
        return {
          title: t('header.statistics'),
          body: <StatisticsPanel stats={stats} coverage={coverage} channels={channels} monthlyData={monthlyData} />,
        };
      case 'processing':
        return {
          title: t('header.processing'),
          headerExtra: (
            <>
              <button disabled={busy} onClick={() => runAction(refreshDates, t('msg.dateRefreshQueued'))}>
                {t('header.missingDates')}
              </button>
              <button disabled={busy} onClick={() => runAction(refreshThumbnails, t('msg.thumbnailRefreshQueued'))}>
                {t('header.missingImages')}
              </button>
              <button
                disabled={busy}
                onClick={() => runAction(
                  () => generateAiNotes(),
                  result => !result.queued
                    ? t('msg.aiBatchRunning', { jobId: result.job_id.slice(0, 8) })
                    : t('msg.aiQueued', { count: result.limit ?? aiBatchLimit })
                )}
              >
                {t('header.aiNotes')}
              </button>
            </>
          ),
          body: (
            <>
              {/* Fetch queue */}
              <div className="queue-section">
                <StatusLine
                  title={t('label.fetcher')}
                  queueSize={fetcherStatus?.queue_size ?? 0}
                  queueStats={fetchQueue}
                  workerCount={fetchWorkers}
                  current={fetcherStatus?.current_task}
                  stopped={!!stoppedQueues.fetch}
                  onStop={() => runAction(() => stopProcessing('fetch'), t('msg.queueRefreshed'))}
                  onStart={() => runAction(() => resumeProcessing('fetch'), t('msg.queueRefreshed'))}
                />
                <JobQueuePanel jobs={jobs.filter(j => j.queue === 'fetch')} busy={busy} onAction={runJobAction} />
              </div>

              {/* Quick Notes queue */}
              <div className="queue-section">
                <StatusLine
                  title={t('label.quickWorker')}
                  queueSize={fetcherStatus?.quick_queue_size ?? 0}
                  queueStats={quickQueue}
                  workerCount={quickWorkers}
                  current={fetcherStatus?.current_quick_task}
                  stopped={!!stoppedQueues.quick}
                  onStop={() => runAction(() => stopProcessing('quick'), t('msg.queueRefreshed'))}
                  onStart={() => runAction(() => resumeProcessing('quick'), t('msg.queueRefreshed'))}
                />
                <JobQueuePanel jobs={jobs.filter(j => j.queue === 'quick')} busy={busy} onAction={runJobAction} />
              </div>

              {/* AI Notes queue */}
              <div className="queue-section">
                <StatusLine
                  title={t('label.aiWorker')}
                  queueSize={fetcherStatus?.ai_queue_size ?? 0}
                  queueStats={aiQueue}
                  workerCount={aiWorkers}
                  current={fetcherStatus?.current_ai_task}
                  stopped={!!stoppedQueues.ai}
                  onStop={() => runAction(() => stopProcessing('ai'), t('msg.queueRefreshed'))}
                  onStart={() => runAction(() => resumeProcessing('ai'), t('msg.queueRefreshed'))}
                />
                <div className={`ai-status-panel ai-status-${aiStatus.tone}`}>
                  <div className="ai-status-main">
                    <div className="ai-status-kicker">{t('header.aiStatus')}</div>
                    <strong>{aiStatus.title}</strong>
                    <p>{aiStatus.detail}</p>
                  </div>
                  <div className="ai-status-side">
                    <span className="ai-status-pill">{t('metric.missingAi')}: {missingAiNotes}</span>
                    <span className="ai-status-pill">{t('label.queueBreakdown', {
                      queued: Number(aiQueue.queued ?? 0),
                      running: Number(aiQueue.running ?? 0),
                      paused: Number(aiQueue.paused ?? 0),
                    })}</span>
                    <span className="ai-status-pill">{t('label.aiBatchLimit')}: {aiBatchLimit}</span>
                    <button
                      disabled={busy || !aiCanStart}
                      onClick={() => runAction(
                        () => generateAiNotes(),
                        result => !result.queued
                          ? t('msg.aiBatchRunning', { jobId: result.job_id.slice(0, 8) })
                          : t('msg.aiQueued', { count: result.limit ?? aiBatchLimit })
                      )}
                    >
                      {t('btn.generateMissing')}
                    </button>
                  </div>
                </div>
                <JobQueuePanel jobs={jobs.filter(j => j.queue === 'ai')} busy={busy} onAction={runJobAction} />
              </div>

              {/* Whisper + Resource cards */}
              <div className="queue-section">
                <StatusLine
                  title={t('label.whisper')}
                  queueSize={whisperStatus?.queue_size ?? 0}
                  current={whisperStatus?.current_task}
                  onStop={() => runAction(stopWhisper, t('msg.queueRefreshed'))}
                />
              </div>
              <div className="resource-panel">
                <div className="resource-card">
                  <span>{t('resource.ollama')}</span>
                  <strong>{ollamaStatus.online ? t('status.running') : t('status.empty')}</strong>
                  <p>{ollamaStatus.online ? (primaryOllamaModel?.name || t('resource.noLoadedModel')) : (ollamaStatus.error || t('resource.notAvailable'))}</p>
                  <small>{t('resource.refreshedAt', { time: sampledAt })}</small>
                </div>
                <div className="resource-card">
                  <span>{t('resource.gpu')}</span>
                  <strong>{processorPercent == null ? '-' : `${processorPercent}%`}</strong>
                  <p>{primaryOllamaModel ? t('resource.vramUsage', {
                    used: formatBytes(primaryOllamaModel.size_vram),
                    total: formatBytes(primaryOllamaModel.size),
                  }) : t('resource.noLoadedModel')}</p>
                  <small>{t('resource.realtimeHint')}</small>
                </div>
                <div className="resource-card">
                  <span>{t('resource.aiWorker')}</span>
                  <strong>{resourceStatus.ai_worker_enabled ? t('status.running') : t('status.paused')}</strong>
                  <p>{t('resource.workerDetails', {
                    workers: aiWorkers ?? 0,
                    queued: Number(aiQueue.queued ?? 0),
                    running: Number(aiQueue.running ?? 0),
                  })}</p>
                  <small>{t('resource.cooldown', { seconds: resourceStatus.ai_job_cooldown_seconds ?? appSettings.ai_notes_job_cooldown_seconds })}</small>
                </div>
              </div>
            </>
          ),
        };
      case 'schedule':
        return {
          title: t('header.schedule'),
          subtitle: `${scheduleCron} · ${scheduleTimezone}`,
          body: (
            <form className="schedule-form" onSubmit={saveSchedule}>
              <label>
                {t('label.dailyRefresh')}
                <input type="time" value={scheduleTime} onChange={e => setScheduleTime(e.target.value)} />
              </label>
              <label>
                {t('label.timezone')}
                <select value={scheduleTimezone} onChange={e => setScheduleTimezone(e.target.value)}>
                  <option value="Europe/Budapest">Europe/Budapest</option>
                  <option value="UTC">UTC</option>
                  <option value="Europe/London">Europe/London</option>
                  <option value="Europe/Berlin">Europe/Berlin</option>
                  <option value="America/New_York">America/New_York</option>
                </select>
              </label>
              <button type="submit" disabled={busy}>{t('btn.save')}</button>
            </form>
          ),
        };
      case 'setup':
        return {
          title: t('header.setup'),
          subtitle: (
            <>
              {appSettings.ai_notes_auto ? t('label.aiAutoOn') : t('label.aiManualOnly')}
              {' · '}
              {appSettings.ai_provider !== 'ollama' ? appSettings.ai_cloud_model : appSettings.ollama_chat_model}
              {appSettings.ai_provider !== 'ollama' && ` (${appSettings.ai_provider})`}
            </>
          ),
          body: (
            <SettingsForm
              settingsDraft={settingsDraft}
              settingsDirty={settingsDirty}
              busy={busy}
              onChange={updateSettingsDraft}
              onSubmit={saveAppSettings}
              onCancel={() => {
                settingsDirtyRef.current = false;
                setSettingsDirty(false);
                setSettingsDraft(appSettings);
              }}
            />
          ),
        };
      case 'quickActions':
        return {
          title: t('header.quickActions'),
          body: <TopActions channels={channels} selectedChannel={selectedChannel} onChannelsChanged={onChannelsChanged} />,
        };
      case 'channelAdmin':
        return {
          title: t('header.channelAdmin'),
          subtitle: t('header.channelAdminSub', { count: channels.length }),
          body: (
            <ChannelAdminPanel
              channels={channels}
              onChanged={async () => {
                await onChannelsChanged();
                await loadAdminData();
              }}
            />
          ),
        };
      default:
        return {};
    }
  }

  return (
    <section className="admin-dashboard">
      <div className="view-header">
        <div>
          <h2>{t('header.admin')}</h2>
          <p>{t('header.adminSub', { channels: channelCount, videos: displayedTotalVideos })}</p>
        </div>
      </div>

      {msg && <div className={`status-msg ${msg.isError ? 'status-error' : 'status-success'}`}>{msg.text}</div>}

      <div className="metric-grid">
        <div className="metric-card">
          <span>{t('metric.todayVideos')}</span>
          <strong>{stats?.todayVideos ?? '-'}</strong>
        </div>
        <div className="metric-card">
          <span>{t('metric.totalVideos')}</span>
          <strong>{displayedTotalVideos}</strong>
        </div>
        <div className="metric-card">
          <span>{t('metric.missingTranscripts')}</span>
          <strong>{stats?.missingTranscripts ?? '-'}</strong>
        </div>
        <div className="metric-card">
          <span>{t('metric.missingAi')}</span>
          <strong>{stats?.missingAiNotes ?? '-'}</strong>
        </div>
        <div className="metric-card">
          <span>{t('metric.errorVideos')}</span>
          <strong>{stats?.errorVideos ?? '-'}</strong>
        </div>
      </div>

      {sectionPrefs.order.map(id => {
        const { title, subtitle, headerExtra, body } = getSectionConfig(id);
        return (
          <CollapsibleSection
            key={id}
            id={id}
            title={title}
            subtitle={subtitle}
            headerExtra={headerExtra}
            open={sectionPrefs.collapsed[id] !== true}
            onToggle={toggleSection}
            isDragging={draggedSectionId !== null}
            isDragOver={dragOverSectionId === id}
            onDragStart={handleSectionDragStart}
            onDragEnd={handleSectionDragEnd}
            onDragOver={handleSectionDragOver}
            onDragLeave={handleSectionDragLeave}
            onDrop={handleSectionDrop}
          >
            {body}
          </CollapsibleSection>
        );
      })}
    </section>
  );
}
