import { useState, useMemo } from 'react';
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  flexRender,
  createColumnHelper,
} from '@tanstack/react-table';
import { videoToTxt, videoToMd, downloadFile, sanitizeFilename } from '../lib/export.js';

const col = createColumnHelper();

function formatDuration(seconds) {
  if (!seconds) return '—';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${m}:${String(s).padStart(2, '0')}`;
}

function formatDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('hu-HU');
}

const STATUS_ICONS = {
  done: '✅',
  pending: '⏳',
  processing: '🔄',
  no_transcript: '—',
  error: '⚠️',
};

export default function VideoTable({ videos, loading, onSelectVideo, selectedChannel }) {
  const [sorting, setSorting] = useState([{ id: 'uploaded_at', desc: true }]);
  const [globalFilter, setGlobalFilter] = useState('');

  const columns = useMemo(() => [
    col.accessor('title', {
      header: 'Cím',
      cell: info => (
        <a
          href={info.row.original.url}
          target="_blank"
          rel="noopener noreferrer"
          style={{ color: '#64b5f6', textDecoration: 'none' }}
          onClick={e => e.stopPropagation()}
        >
          {info.getValue() || 'Ismeretlen'}
        </a>
      ),
      size: 400,
    }),
    col.accessor('uploaded_at', {
      header: 'Feltöltve',
      cell: info => formatDate(info.getValue()),
      size: 100,
    }),
    col.accessor('duration_seconds', {
      header: 'Hossz',
      cell: info => formatDuration(info.getValue()),
      size: 80,
    }),
    col.accessor('status', {
      header: 'Állapot',
      cell: info => {
        const s = info.getValue();
        return (
          <span className={`badge badge-${s}`}>
            {STATUS_ICONS[s] || ''} {s === 'no_transcript' ? 'Nincs' : s === 'done' ? 'Kész' : s === 'pending' ? 'Várakozik' : s === 'error' ? 'Hiba' : s}
          </span>
        );
      },
      size: 100,
    }),
    col.display({
      id: 'actions',
      header: '',
      cell: info => {
        const video = info.row.original;
        return (
          <div style={{ display: 'flex', gap: '0.3rem' }}>
            {video.transcript && (
              <button
                style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem' }}
                onClick={e => { e.stopPropagation(); onSelectVideo(video); }}
              >
                Transzkript
              </button>
            )}
            <button
              style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem' }}
              onClick={e => {
                e.stopPropagation();
                downloadFile(videoToTxt(video), `${sanitizeFilename(video.title)}.txt`);
              }}
            >
              TXT
            </button>
            <button
              style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem' }}
              onClick={e => {
                e.stopPropagation();
                downloadFile(videoToMd(video), `${sanitizeFilename(video.title)}.md`);
              }}
            >
              MD
            </button>
          </div>
        );
      },
      size: 180,
    }),
  ], [onSelectVideo]);

  const table = useReactTable({
    data: videos,
    columns,
    state: { sorting, globalFilter },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
        <h2 style={{ fontSize: '1rem', fontWeight: 600 }}>
          {selectedChannel
            ? `${selectedChannel.name || selectedChannel.channel_handle} — ${videos.length} videó`
            : `Összes videó (${videos.length})`
          }
        </h2>
        <input
          placeholder="Keresés..."
          value={globalFilter}
          onChange={e => setGlobalFilter(e.target.value)}
          style={{ width: '200px' }}
        />
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: '2rem', color: '#888' }}>Betöltés...</div>
      ) : videos.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '2rem', color: '#666' }}>
          Nincsenek videók. Adj hozzá egy csatornát a bal oldalon.
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
            <thead>
              {table.getHeaderGroups().map(hg => (
                <tr key={hg.id} style={{ borderBottom: '1px solid var(--border)' }}>
                  {hg.headers.map(header => (
                    <th
                      key={header.id}
                      style={{
                        padding: '0.5rem 0.75rem',
                        textAlign: 'left',
                        fontWeight: 600,
                        color: '#aaa',
                        whiteSpace: 'nowrap',
                        cursor: header.column.getCanSort() ? 'pointer' : 'default',
                        userSelect: 'none',
                        width: header.getSize(),
                      }}
                      onClick={header.column.getToggleSortingHandler()}
                    >
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      {header.column.getIsSorted() === 'asc' && ' ↑'}
                      {header.column.getIsSorted() === 'desc' && ' ↓'}
                    </th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.map((row, i) => (
                <tr
                  key={row.id}
                  style={{
                    background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.02)',
                    borderBottom: '1px solid rgba(255,255,255,0.05)',
                    cursor: row.original.transcript ? 'pointer' : 'default',
                  }}
                  onClick={() => row.original.transcript && onSelectVideo(row.original)}
                >
                  {row.getVisibleCells().map(cell => (
                    <td key={cell.id} style={{ padding: '0.5rem 0.75rem', verticalAlign: 'middle' }}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
