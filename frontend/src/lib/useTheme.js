import { useState } from 'react';

export function useTheme() {
  const [theme, setTheme] = useState(() => localStorage.getItem('yt_theme') || 'dark');

  function handleThemeToggle() {
    const next = theme === 'dark' ? 'light' : 'dark';
    setTheme(next);
    localStorage.setItem('yt_theme', next);
    if (next === 'light') document.documentElement.setAttribute('data-theme', 'light');
    else document.documentElement.removeAttribute('data-theme');
  }

  return { theme, handleThemeToggle };
}
