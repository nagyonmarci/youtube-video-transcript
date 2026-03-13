import { useState, useEffect } from "react";
import { getVideos } from "../api/client";

const STATUS_LABELS = {
  done: "✅ Kész",
  pending: "⏳ Folyamatban",
  no_transcript: "❌ Nincs felirat",
  error: "⚠️ Hiba",
};

function formatDuration(seconds) {
  if (!seconds) return "–";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function formatDate(iso) {
  if (!iso) return "–";
  return new Date(iso).toLocaleDateString("hu-HU", {
    year: "numeric", month: "short", day: "numeric",
  });
}

function SortIcon({ column, sortKey, sortDir }) {
  if (sortKey !== column) return <span className="sort-icon">↕</span>;
  return <span className="sort-icon">{sortDir === "asc" ? "↑" : "↓"}</span>;
}

export default function VideoList({ channel, onSelectVideo }) {
  const [videos, setVideos] = useState([]);
  const [filter, setFilter] = useState("");
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState("uploaded_at");
  const [sortDir, setSortDir] = useState("desc");

  function loadVideos() {
    if (!channel) return;
    getVideos(channel, filter).then(setVideos);
  }

  useEffect(() => {
    loadVideos();
    const interval = setInterval(loadVideos, 10000); // 10mp-ként frissül
    return () => clearInterval(interval);
  }, [channel, filter]);

  function handleSort(key) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  const filtered = videos
    .filter((v) => v.title?.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => {
      let aVal = a[sortKey];
      let bVal = b[sortKey];

      // null értékek mindig a végére
      if (aVal == null) return 1;
      if (bVal == null) return -1;

      // dátum és szám összehasonlítás
      if (sortKey === "uploaded_at") {
        aVal = new Date(aVal).getTime();
        bVal = new Date(bVal).getTime();
      }

      if (typeof aVal === "string") {
        return sortDir === "asc"
          ? aVal.localeCompare(bVal)
          : bVal.localeCompare(aVal);
      }

      return sortDir === "asc" ? aVal - bVal : bVal - aVal;
    });

  if (!channel) return null;

  const cols = [
    { key: "title",       label: "Cím" },
    { key: "uploaded_at", label: "Feltöltve" },
    { key: "duration",    label: "Hossz" },
    { key: "status",      label: "Státusz" },
  ];

  return (
    <div className="card">
      <h2>Videók — {channel}</h2>
      <div className="row">
        <input
          placeholder="Keresés a címben..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">Összes státusz</option>
          <option value="done">Kész</option>
          <option value="pending">Folyamatban</option>
          <option value="no_transcript">Nincs felirat</option>
          <option value="error">Hiba</option>
        </select>
      </div>

      <table>
        <thead>
          <tr>
            {cols.map((col) => (
              <th
                key={col.key}
                onClick={() => handleSort(col.key)}
                className="sortable"
              >
                {col.label}
                <SortIcon column={col.key} sortKey={sortKey} sortDir={sortDir} />
              </th>
            ))}
            <th></th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((v) => (
            <tr key={v.video_id}>
              <td>
                <a href={v.url} target="_blank" rel="noreferrer">{v.title}</a>
              </td>
              <td>{formatDate(v.uploaded_at)}</td>
              <td>{formatDuration(v.duration)}</td>
              <td>{STATUS_LABELS[v.status] ?? v.status}</td>
              <td>
                {v.status === "done" && (
                  <button onClick={() => onSelectVideo(v.video_id)}>
                    Transzkript
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!filtered.length && <p className="muted">Nincs találat.</p>}
    </div>
  );
}
