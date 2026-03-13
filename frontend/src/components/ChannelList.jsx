import { deleteChannel } from "../api/client";

const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

export default function ChannelList({ channels, onSelect, selected, onDeleted }) {

  async function handleDelete(name) {
    if (!confirm(`Are you sure you want to delete the channel "${name}"?`)) return;
    await deleteChannel(name);
    onDeleted();
  }

  function handleExport(name) {
    const token = localStorage.getItem("yt_token");
    window.open(`${BASE}/channels/${name}/export?token=${token}`, "_blank");
  }

  function handleRefreshMetadata(name) {
    fetch(`${BASE}/channels/${name}/refresh-metadata`, { 
      method: "POST",
      headers: { "Authorization": `Bearer ${localStorage.getItem("yt_token")}` }
    })
      .then(() => alert(`Metadata refresh for "${name}" has started.`));
  }

  function handleSaveToDrive(name) {
    const fmt = confirm("Use Markdown format? (Cancel for TXT)") ? "md" : "txt";
    
    // Request access token for Drive
    // @ts-ignore
    const client = google.accounts.oauth2.initTokenClient({
      client_id: import.meta.env.VITE_GOOGLE_CLIENT_ID || '',
      scope: 'https://www.googleapis.com/auth/drive.file',
      callback: async (tokenResponse) => {
        if (tokenResponse.error) {
          alert("Drive authorization failed.");
          return;
        }
        
        try {
          const res = await fetch(`${BASE}/channels/${name}/save-to-drive`, {
            method: "POST",
            headers: { 
              "Content-Type": "application/json",
              "Authorization": `Bearer ${localStorage.getItem("yt_token")}`
            },
            body: JSON.stringify({ 
              access_token: tokenResponse.access_token,
              format: fmt
            }),
          });
          
          if (!res.ok) throw new Error("Upload failed");
          const data = await res.json();
          alert(`Success! File saved to Drive. ID: ${data.file_id}`);
        } catch (err) {
          alert("Failed to save to Drive. Check console for details.");
          console.error(err);
        }
      },
    });
    client.requestAccessToken();
  }

  if (!channels.length) return <p className="muted">No channels added yet.</p>;

  return (
    <div className="card">
      <h2>Channels</h2>
      <ul className="channel-list">
        {channels.map((ch) => (
          <li
            key={ch.name}
            className={selected === ch.name ? "active" : ""}
            onClick={() => onSelect(ch.name)}
          >
            <span className="name">📺 {ch.name}</span>
            <div className="actions">
              <button
                className="secondary icon-btn"
                title="Export"
                onClick={(e) => { e.stopPropagation(); handleExport(ch.name); }}
              >
                📥
              </button>
              <button
                className="secondary icon-btn"
                title="Refresh Metadata"
                onClick={(e) => { e.stopPropagation(); handleRefreshMetadata(ch.name); }}
              >
                🔄
              </button>
              <button
                className="secondary icon-btn"
                title="Save to Google Drive"
                style={{ background: 'rgba(66, 133, 244, 0.2)', border: '1px solid rgba(66, 133, 244, 0.4)' }}
                onClick={(e) => { e.stopPropagation(); handleSaveToDrive(ch.name); }}
              >
                📁
              </button>
              <button
                className="danger icon-btn"
                title="Delete"
                onClick={(e) => { e.stopPropagation(); handleDelete(ch.name); }}
              >
                🗑️
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
