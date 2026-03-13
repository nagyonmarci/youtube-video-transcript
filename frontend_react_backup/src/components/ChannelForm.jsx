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
      <h2>Csatorna hozzáadása</h2>
      <form onSubmit={handleSubmit} className="row">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="pl. christianlempa"
        />
        <button type="submit" disabled={loading}>
          {loading ? "Hozzáadás..." : "Hozzáadás"}
        </button>
      </form>
      {msg && <p className="info">{msg}</p>}
    </div>
  );
}
