import { useState } from "react";
import { addChannel } from "../api/client";

export default function ChannelForm({ onAdded }) {
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    if (!name.trim()) return;
    setLoading(true);
    const res = await addChannel(name.trim());
    setMsg(`✅ "${res.channel}" sikeresen hozzáadva, feldolgozás folyamatban...`);
    setName("");
    setLoading(false);
    onAdded();
  }

  return (
    <div className="card">
      <h2>✨ Add Channel</h2>
      <form onSubmit={handleSubmit} className="row" style={{ flexWrap: 'wrap' }}>
        <input
          style={{ flex: '1 1 200px' }}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. christianlempa"
        />
        <button type="submit" disabled={loading} style={{ flex: '0 0 auto' }}>
          {loading ? "Adding..." : "➕ Add Channel"}
        </button>
      </form>
      {msg && <p className="info" style={{ marginTop: '0.5rem', color: 'var(--success)', fontSize: '0.85rem' }}>{msg}</p>}
    </div>
  );
}
