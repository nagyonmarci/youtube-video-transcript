import { useMemo, useState } from 'react';
import { deleteChannel, updateChannel } from '../lib/directus.js';
import { generateAiNotesForChannel, refreshChannel } from '../lib/fetcher.js';
import { useT } from '../lib/i18n.jsx';

function editableChannel(ch) {
  return {
    name: ch.name || '',
    channel_url: ch.channel_url || '',
    channel_handle: ch.channel_handle || '',
    status: ch.status || 'pending',
  };
}

export default function ChannelAdminPanel({ channels, onClose, onChanged }) {
  const { t } = useT();

  const STATUS_OPTIONS = [
    { value: 'pending', label: t('status.pending') },
    { value: 'processing', label: t('status.inProgress') },
    { value: 'done', label: t('status.done') },
    { value: 'error', label: t('status.error') },
  ];

  const [search, setSearch] = useState('');
  const [drafts, setDrafts] = useState(() => Object.fromEntries(
    channels.map(ch => [ch.id, editableChannel(ch)])
  ));
  const [busyId, setBusyId] = useState(null);
  const [msg, setMsg] = useState(null);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return channels;
    return channels.filter(ch => (
      `${ch.name || ''} ${ch.channel_handle || ''} ${ch.channel_url || ''}`
        .toLowerCase()
        .includes(q)
    ));
  }, [channels, search]);

  function showMsg(text, isError = false) {
    setMsg({ text, isError });
    setTimeout(() => setMsg(null), 4000);
  }

  function updateDraft(id, field, value) {
    setDrafts(prev => ({
      ...prev,
      [id]: {
        ...(prev[id] || {}),
        [field]: value,
      },
    }));
  }

  async function handleSave(ch) {
    setBusyId(ch.id);
    try {
      const draft = drafts[ch.id] || editableChannel(ch);
      await updateChannel(ch.id, {
        name: draft.name.trim(),
        channel_url: draft.channel_url.trim(),
        channel_handle: draft.channel_handle.trim(),
        status: draft.status,
      });
      showMsg(t('msg.channelSaved'));
      await onChanged();
    } catch (e) {
      showMsg(t('msg.errSave', { error: e.message }), true);
    } finally {
      setBusyId(null);
    }
  }

  async function handleRefresh(ch) {
    setBusyId(ch.id);
    try {
      await refreshChannel(ch.id);
      showMsg(t('msg.refreshQueued'));
      await onChanged();
    } catch (e) {
      showMsg(t('msg.errRefresh', { error: e.message }), true);
    } finally {
      setBusyId(null);
    }
  }

  async function handleGenerateChannelAi(ch) {
    setBusyId(ch.id);
    try {
      const result = await generateAiNotesForChannel(ch.id);
      showMsg(t('msg.aiQueued', { count: result.count }));
      await onChanged();
    } catch (e) {
      showMsg(t('msg.errAi', { error: e.message }), true);
    } finally {
      setBusyId(null);
    }
  }

  async function handleDelete(ch) {
    if (!confirm(t('confirm.deleteChannel', { name: ch.name || ch.channel_handle || ch.channel_url }))) return;
    setBusyId(ch.id);
    try {
      await deleteChannel(ch.id);
      showMsg(t('msg.channelDeleted'));
      await onChanged();
    } catch (e) {
      showMsg(t('msg.errGeneric', { error: e.message }), true);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section className="admin-panel">
      <div className="admin-panel-header">
        <div>
          <h2>{t('header.channelAdmin')}</h2>
          <p>{t('header.channelAdminSub', { count: channels.length })}</p>
        </div>
        {onClose && <button onClick={onClose}>{t('btn.close')}</button>}
      </div>

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
                <td colSpan="6" className="admin-empty">{t('state.noResults')}</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
