import type { FormEvent } from 'react';
import { useT } from '../lib/i18n.tsx';
import type { AppSettings } from '../types.ts';

interface SettingsFormProps {
  settingsDraft: AppSettings;
  settingsDirty: boolean;
  busy: boolean;
  onChange: (field: keyof AppSettings, value: string | number | boolean) => void;
  onSubmit: (e: FormEvent<HTMLFormElement>) => void;
  onCancel: () => void;
}

export default function SettingsForm({ settingsDraft, settingsDirty, busy, onChange, onSubmit, onCancel }: SettingsFormProps) {
  const { t } = useT();
  return (
    <form className="settings-form" onSubmit={onSubmit}>
        <label>
          {t('label.ollamaBaseUrl')}
          <input
            value={settingsDraft.ollama_base_url}
            onChange={e => onChange('ollama_base_url', e.target.value)}
            placeholder="http://host.docker.internal:11434"
          />
        </label>
        <label>
          {t('label.ollamaModel')}
          <input
            value={settingsDraft.ollama_chat_model}
            onChange={e => onChange('ollama_chat_model', e.target.value)}
            placeholder="gemma4:31b-mlx-bf16"
          />
        </label>
        <label>
          {t('label.ollamaTimeout')}
          <input
            type="number"
            min="30"
            value={settingsDraft.ollama_timeout}
            onChange={e => onChange('ollama_timeout', Number(e.target.value))}
          />
        </label>
        {settingsDraft.ai_provider === 'ollama' && (
          <>
            <label>
              {t('label.ollamaNumCtx')}
              <input
                type="number"
                min="2048"
                step="1024"
                value={settingsDraft.ollama_num_ctx}
                onChange={e => onChange('ollama_num_ctx', Number(e.target.value))}
              />
            </label>
            <label>
              {t('label.ollamaQuickNumCtx')}
              <input
                type="number"
                min="512"
                step="512"
                value={settingsDraft.ollama_quick_num_ctx}
                onChange={e => onChange('ollama_quick_num_ctx', Number(e.target.value))}
              />
            </label>
            <label>
              {t('label.ollamaTemperature')}
              <input
                type="number"
                min="0"
                max="2"
                step="0.05"
                value={settingsDraft.ollama_temperature}
                onChange={e => onChange('ollama_temperature', Number(e.target.value))}
              />
            </label>
            <label>
              {t('label.ollamaNumPredict')}
              <input
                type="number"
                min="256"
                step="256"
                value={settingsDraft.ollama_num_predict}
                onChange={e => onChange('ollama_num_predict', Number(e.target.value))}
              />
            </label>
          </>
        )}
        <label>
          {t('label.aiMaxChars')}
          <input
            type="number"
            min="1000"
            step="1000"
            value={settingsDraft.ai_notes_max_chars}
            onChange={e => onChange('ai_notes_max_chars', Number(e.target.value))}
          />
        </label>
        <label>
          {t('label.aiProvider')}
          <select
            value={settingsDraft.ai_provider}
            onChange={e => onChange('ai_provider', e.target.value)}
          >
            <option value="ollama">{t('label.aiProviderOllama')}</option>
            <option value="anthropic">{t('label.aiProviderAnthropic')}</option>
            <option value="openai">{t('label.aiProviderOpenai')}</option>
          </select>
        </label>
        {settingsDraft.ai_provider !== 'ollama' && (
          <label>
            {t('label.aiCloudModel')}
            <input
              value={settingsDraft.ai_cloud_model}
              onChange={e => onChange('ai_cloud_model', e.target.value)}
              placeholder="claude-opus-4-7"
            />
          </label>
        )}
        {settingsDraft.ai_provider === 'anthropic' && (
          <label>
            {t('label.anthropicApiKey')}
            <input
              type="password"
              value={settingsDraft.anthropic_api_key}
              onChange={e => onChange('anthropic_api_key', e.target.value)}
              placeholder="sk-ant-..."
              autoComplete="off"
            />
          </label>
        )}
        {settingsDraft.ai_provider === 'openai' && (
          <>
            <label>
              {t('label.openaiApiKey')}
              <input
                type="password"
                value={settingsDraft.openai_api_key}
                onChange={e => onChange('openai_api_key', e.target.value)}
                placeholder="sk-..."
                autoComplete="off"
              />
            </label>
            <label>
              {t('label.openaiBaseUrl')}
              <input
                value={settingsDraft.openai_base_url}
                onChange={e => onChange('openai_base_url', e.target.value)}
                placeholder="https://api.openai.com/v1"
              />
            </label>
          </>
        )}
        <label>
          {t('label.aiQuickModel')}
          <input
            value={settingsDraft.ollama_quick_model}
            onChange={e => onChange('ollama_quick_model', e.target.value)}
            placeholder="qwen3:4b"
          />
        </label>
        <label>
          {t('label.aiQuickTimeout')}
          <input
            type="number"
            min="10"
            value={settingsDraft.ollama_quick_timeout}
            onChange={e => onChange('ollama_quick_timeout', Number(e.target.value))}
          />
        </label>
        <label>
          {t('label.aiBatchLimit')}
          <input
            type="number"
            min="1"
            value={settingsDraft.ai_notes_batch_limit}
            onChange={e => onChange('ai_notes_batch_limit', Number(e.target.value))}
          />
        </label>
        <label>
          {t('label.aiMaxBatchLimit')}
          <input
            type="number"
            min="1"
            value={settingsDraft.ai_notes_max_batch_limit}
            onChange={e => onChange('ai_notes_max_batch_limit', Number(e.target.value))}
          />
        </label>
        <label>
          {t('label.aiBackfillYear')}
          <input
            type="number"
            min="0"
            value={settingsDraft.ai_notes_year_backfill_year}
            onChange={e => onChange('ai_notes_year_backfill_year', Number(e.target.value))}
          />
        </label>
        <label>
          {t('label.aiBackfillBatch')}
          <input
            type="number"
            min="1"
            value={settingsDraft.ai_notes_year_backfill_batch_limit}
            onChange={e => onChange('ai_notes_year_backfill_batch_limit', Number(e.target.value))}
          />
        </label>
        <label>
          {t('label.aiBackfillTarget')}
          <input
            type="number"
            min="1"
            value={settingsDraft.ai_notes_year_backfill_target_active}
            onChange={e => onChange('ai_notes_year_backfill_target_active', Number(e.target.value))}
          />
        </label>
        <label>
          {t('label.aiBackfillInterval')}
          <input
            type="number"
            min="30"
            value={settingsDraft.ai_notes_year_backfill_interval_seconds}
            onChange={e => onChange('ai_notes_year_backfill_interval_seconds', Number(e.target.value))}
          />
        </label>
        <label>
          {t('label.aiJobCooldown')}
          <input
            type="number"
            min="0"
            max="3600"
            value={settingsDraft.ai_notes_job_cooldown_seconds}
            onChange={e => onChange('ai_notes_job_cooldown_seconds', Number(e.target.value))}
          />
        </label>
        <label className="settings-check">
          <input
            type="checkbox"
            checked={settingsDraft.ai_notes_worker_enabled}
            onChange={e => onChange('ai_notes_worker_enabled', e.target.checked)}
          />
          {t('label.aiWorkerEnabled')}
        </label>
        <label className="settings-check">
          <input
            type="checkbox"
            checked={settingsDraft.ai_notes_quick_enabled}
            onChange={e => onChange('ai_notes_quick_enabled', e.target.checked)}
          />
          {t('label.aiQuickEnabled')}
        </label>
        <label className="settings-check">
          <input
            type="checkbox"
            checked={settingsDraft.ai_notes_auto}
            onChange={e => onChange('ai_notes_auto', e.target.checked)}
          />
          {t('label.aiAutoAfterTranscript')}
        </label>
        <label className="settings-check">
          <input
            type="checkbox"
            checked={settingsDraft.ai_notes_year_backfill_enabled}
            onChange={e => onChange('ai_notes_year_backfill_enabled', e.target.checked)}
          />
          {t('label.aiYearBackfill')}
        </label>
        <label className="settings-check">
          <input
            type="checkbox"
            checked={settingsDraft.ai_night_window_enabled}
            onChange={e => onChange('ai_night_window_enabled', e.target.checked)}
          />
          {t('label.aiNightWindowEnabled')}
        </label>
        {settingsDraft.ai_night_window_enabled && (
          <>
            <label>
              {t('label.aiNightWindowStart')}
              <input
                type="number"
                min="0"
                max="23"
                value={settingsDraft.ai_night_window_start_hour}
                onChange={e => onChange('ai_night_window_start_hour', Number(e.target.value))}
              />
            </label>
            <label>
              {t('label.aiNightWindowStop')}
              <input
                type="number"
                min="0"
                max="23"
                value={settingsDraft.ai_night_window_stop_hour}
                onChange={e => onChange('ai_night_window_stop_hour', Number(e.target.value))}
              />
            </label>
          </>
        )}
        <label>
          {t('label.channelJobVideoCap')}
          <input
            type="number"
            min="1"
            value={settingsDraft.channel_job_video_cap}
            onChange={e => onChange('channel_job_video_cap', Number(e.target.value))}
          />
        </label>
        <label className="settings-check">
          <input
            type="checkbox"
            checked={settingsDraft.channel_backlog_window_enabled}
            onChange={e => onChange('channel_backlog_window_enabled', e.target.checked)}
          />
          {t('label.channelBacklogWindowEnabled')}
        </label>
        {settingsDraft.channel_backlog_window_enabled && (
          <>
            <label>
              {t('label.channelBacklogStart')}
              <input
                type="number"
                min="0"
                max="23"
                value={settingsDraft.channel_backlog_start_hour}
                onChange={e => onChange('channel_backlog_start_hour', Number(e.target.value))}
              />
            </label>
            <label>
              {t('label.channelBacklogStop')}
              <input
                type="number"
                min="0"
                max="23"
                value={settingsDraft.channel_backlog_stop_hour}
                onChange={e => onChange('channel_backlog_stop_hour', Number(e.target.value))}
              />
            </label>
          </>
        )}
        <div className="settings-actions">
          <button type="submit" disabled={busy || !settingsDirty}>{t('btn.save')}</button>
          <button type="button" disabled={busy || !settingsDirty} onClick={onCancel}>{t('btn.cancel')}</button>
        </div>
      </form>
  );
}
