import { createContext, useContext, useState } from 'react';
import en from '../locales/en.json';
import hu from '../locales/hu.json';

const translations = { en, hu };

function resolve(obj, key) {
  return key.split('.').reduce((o, k) => o?.[k], obj);
}

function interpolate(str, vars) {
  if (!vars) return str;
  return Object.entries(vars).reduce((s, [k, v]) => s.replaceAll(`{${k}}`, String(v)), str);
}

const I18nContext = createContext(null);

export function I18nProvider({ children }) {
  const [lang, setLang] = useState(() => {
    try { return localStorage.getItem('lang') || 'hu'; } catch { return 'hu'; }
  });

  function t(key, vars) {
    const val = resolve(translations[lang], key) ?? resolve(translations.en, key) ?? key;
    return typeof val === 'string' ? interpolate(val, vars) : (val ?? key);
  }

  function setLanguage(l) {
    setLang(l);
    try { localStorage.setItem('lang', l); } catch {}
  }

  return (
    <I18nContext.Provider value={{ lang, t, setLanguage }}>
      {children}
    </I18nContext.Provider>
  );
}

export function useT() {
  return useContext(I18nContext);
}
