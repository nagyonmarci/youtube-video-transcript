import { deleteChannel } from "../api/client";

const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

export default function ChannelList({ channels, onSelect, selected, onDeleted }) {
  async function handleDelete(name) {
    if (!confirm(`Törlöd a(z) "${name}" csatornát?`)) return;
    await deleteChannel(name);
    onDeleted();
  }

  function handleExport(name) {
    window.open(`${BASE}/channels/${name}/export`, "_blank");
  }

  function handleRefreshMetadata(name) {
    fetch(`${BASE}/channels/${name}/refresh-metadata`, { method: "POST" })
      .then(() => alert(`"${name}" metaadatok frissítése elindult.`));
  }

  if (!channels.length) return <p className="muted">Még nincs hozzáadott csatorna.</p>;

  return (
    <div className="card">
      <h2>Csatornák</h2>
      <ul className="channel-list">
        {channels.map((ch) => (
          <li
            key={ch.name}
            className={selected === ch.name ? "active" : ""}
            onClick={() => onSelect(ch.name)}
          >
            <span>📺 {ch.name}</span>
            <div className="btn-group">
              <button
                className="export"
                onClick={(e) => { e.stopPropagation(); handleExport(ch.name); }}
              >
                ⬇ Export
              </button>
              <button
                className="refresh"
                onClick={(e) => { e.stopPropagation(); handleRefreshMetadata(ch.name); }}
              >
                🔄 Metaadat
              </button>
              <button
                className="danger"
                onClick={(e) => { e.stopPropagation(); handleDelete(ch.name); }}
              >
                Törlés
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
