import { useEffect, useMemo, useState } from 'react';
import { deleteChannel, updateChannel } from '../lib/directus.ts';
import { generateAiNotesForChannel, refreshChannel } from '../lib/fetcher.ts';
import { useT } from '../lib/i18n.tsx';
import { useMessage } from '../lib/useMessage.ts';
import type { Channel } from '../types.ts';

interface EditableChannel {
  name: string;
  topic: string;
  channel_url: string;
  channel_handle: string;
  status: string;
}

function editableChannel(ch: Channel): EditableChannel {
  return {
    name: ch.name || '',
    topic: ch.topic || '',
    channel_url: ch.channel_url || '',
    channel_handle: ch.channel_handle || '',
    status: ch.status || 'pending',
  };
}

interface ChannelAdminPanelProps {
  channels: Channel[];
  onChanged: () => Promise<void> | void;
}

export default function ChannelAdminPanel({ channels, onChanged }: ChannelAdminPanelProps) {
  const { t } = useT();

  const STATUS_OPTIONS = [
    { value: 'pending', label: t('status.pending') },
    { value: 'processing', label: t('status.inProgress') },
    { value: 'done', label: t('status.done') },
    { value: 'error', label: t('status.error') },
  ];

  const [search, setSearch] = useState('');
  const [drafts, setDrafts] = useState<Record<string, EditableChannel>>(() => Object.fromEntries(
    channels.map(ch => [ch.id, editableChannel(ch)])
  ));
  useEffect(() => {
    setDrafts(prev => {
      const next: Record<string, EditableChannel> = {};
      channels.forEach(ch => {
        next[ch.id] = {
          ...editableChannel(ch),
          ...(prev[ch.id] || {}),
        };
      });
      return next;
    });
  }, [channels]);

  const [busyId, setBusyId] = useState<string | null>(null);
  const { msg, showMsg } = useMessage();

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return channels;
    return channels.filter(ch => (
      `${ch.name || ''} ${ch.topic || ''} ${ch.channel_handle || ''} ${ch.channel_url || ''}`
        .toLowerCase()
        .includes(q)
    ));
  }, [channels, search]);

  function updateDraft(id: string, field: keyof EditableChannel, value: string) {
    setDrafts(prev => ({
      ...prev,
      [id]: {
        ...(prev[id] || {}),
        [field]: value,
      },
    }));
  }

  async function handleSave(ch: Channel) {
    setBusyId(ch.id);
    try {
      const draft = {
        ...editableChannel(ch),
        ...(drafts[ch.id] || {}),
      };
      await updateChannel(ch.id, {
        name: draft.name.trim(),
        topic: draft.topic.trim(),
        channel_url: draft.channel_url.trim(),
        channel_handle: draft.channel_handle.trim(),
        status: draft.status as Channel['status'],
      });
      showMsg(t('msg.channelSaved'));
      await onChanged();
    } catch (e) {
      showMsg(t('msg.errSave', { error: (e as Error).message }), true);
    } finally {
      setBusyId(null);
    }
  }

  async function handleRefresh(ch: Channel) {
    setBusyId(ch.id);
    try {
      await refreshChannel(ch.id);
      showMsg(t('msg.refreshQueued'));
      await onChanged();
    } catch (e) {
      showMsg(t('msg.errRefresh', { error: (e as Error).message }), true);
    } finally {
      setBusyId(null);
    }
  }

  async function handleGenerateChannelAi(ch: Channel) {
    setBusyId(ch.id);
    try {
      const result = await generateAiNotesForChannel(ch.id);
      showMsg(t('msg.aiQueued', { count: result.count }));
      await onChanged();
    } catch (e) {
      showMsg(t('msg.errAi', { error: (e as Error).message }), true);
    } finally {
      setBusyId(null);
    }
  }

  async function handleDelete(ch: Channel) {
    if (!confirm(t('confirm.deleteChannel', { name: ch.name || ch.channel_handle || ch.channel_url }))) return;
    setBusyId(ch.id);
    try {
      await deleteChannel(ch.id);
      showMsg(t('msg.channelDeleted'));
      await onChanged();
    } catch (e) {
      showMsg(t('msg.errGeneric', { error: (e as Error).message }), true);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <>
      <div className="admin-toolbar">
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder={t('placeholder.searchChannelAdmin')}
        />
      </div>

      {msg && (
        <div className={`status-msg ${msg.isError ? 'status-error' : 'status-success'}`}>
          {msg.text}
        </div>
      )}

      <div className="admin-table-wrap">
        <table className="admin-table">
          <thead>
            <tr>
              <th>{t('label.name')}</th>
              <th>{t('label.topic')}</th>
              <th>{t('label.url')}</th>
              <th>{t('label.handle')}</th>
              <th>{t('label.status')}</th>
              <th>{t('label.videos')}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(ch => {
              const draft = drafts[ch.id] || editableChannel(ch);
              const busy = busyId === ch.id;
              return (
                <tr key={ch.id}>
                  <td>
                    <input
                      value={draft.name}
                      onChange={e => updateDraft(ch.id, 'name', e.target.value)}
                    />
                  </td>
                  <td>
                    <input
                      value={draft.topic}
                      onChange={e => updateDraft(ch.id, 'topic', e.target.value)}
                      placeholder={t('placeholder.channelTopic')}
                    />
                  </td>
                  <td>
                    <input
                      value={draft.channel_url}
                      onChange={e => updateDraft(ch.id, 'channel_url', e.target.value)}
                    />
                  </td>
                  <td>
                    <input
                      value={draft.channel_handle}
                      onChange={e => updateDraft(ch.id, 'channel_handle', e.target.value)}
                    />
                  </td>
                  <td>
                    <select
                      value={draft.status}
                      onChange={e => updateDraft(ch.id, 'status', e.target.value)}
                    >
                      {STATUS_OPTIONS.map(option => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                      ))}
                    </select>
                  </td>
                  <td className="admin-count">{ch.video_count || 0}</td>
                  <td>
                    <div className="admin-row-actions">
                      <button onClick={() => handleSave(ch)} disabled={busy}>{t('btn.save')}</button>
                      <button onClick={() => handleRefresh(ch)} disabled={busy}>{t('btn.refresh')}</button>
                      <button onClick={() => handleGenerateChannelAi(ch)} disabled={busy}>{t('header.aiNotes')}</button>
                      <button className="danger" onClick={() => handleDelete(ch)} disabled={busy}>{t('btn.delete')}</button>
                    </div>
                  </td>
                </tr>
              );
            })}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={7} className="admin-empty">{t('state.noResults')}</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}
