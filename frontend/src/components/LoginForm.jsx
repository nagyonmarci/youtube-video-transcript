import { useState } from 'react';

const DIRECTUS_URL = import.meta.env.PUBLIC_DIRECTUS_URL || 'http://localhost:8055';

export default function LoginForm() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await fetch(`${DIRECTUS_URL}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data?.errors?.[0]?.message || 'Hibás email vagy jelszó.');
        return;
      }
      localStorage.setItem('directus_token', data.data.access_token);
      localStorage.setItem('directus_refresh_token', data.data.refresh_token);
      window.location.href = '/';
    } catch {
      setError('Hálózati hiba. Ellenőrizd a kapcsolatot.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: 'var(--bg)',
    }}>
      <div style={{
        background: 'var(--bg2)',
        border: '1px solid var(--border)',
        borderRadius: '12px',
        padding: '2rem',
        width: '100%',
        maxWidth: '360px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', marginBottom: '1.5rem' }}>
          <span style={{ fontSize: '1.6rem' }}>▶</span>
          <h1 style={{ fontSize: '1.1rem', fontWeight: 700 }}>YouTube Transcript</h1>
        </div>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text2)', marginBottom: '0.3rem' }}>
              Email
            </label>
            <input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
              autoFocus
              placeholder="email@cím.hu"
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text2)', marginBottom: '0.3rem' }}>
              Jelszó
            </label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
              placeholder="jelszó"
            />
          </div>

          {error && (
            <div style={{
              background: 'rgba(244,67,54,0.15)',
              border: '1px solid rgba(244,67,54,0.3)',
              borderRadius: '6px',
              padding: '0.5rem 0.75rem',
              fontSize: '0.82rem',
              color: '#f88',
            }}>
              {error}
            </div>
          )}

          <button
            type="submit"
            className="primary"
            disabled={loading}
            style={{ marginTop: '0.25rem', padding: '0.6rem' }}
          >
            {loading ? 'Bejelentkezés...' : 'Bejelentkezés'}
          </button>
        </form>
      </div>
    </div>
  );
}
