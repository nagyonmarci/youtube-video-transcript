import { useState, type FormEvent } from 'react';
import { useT } from '../lib/i18n.tsx';

export default function HeaderSearch() {
  const { t } = useT();
  const [query, setQuery] = useState('');

  function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const q = query.trim();
    if (!q) return;
    window.location.href = `/search?q=${encodeURIComponent(q)}`;
  }

  return (
    <form onSubmit={handleSubmit} className="header-search">
      <input
        type="search"
        placeholder={t('nav.search')}
        value={query}
        onChange={e => setQuery(e.target.value)}
      />
    </form>
  );
}
