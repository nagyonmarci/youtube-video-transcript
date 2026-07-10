import { createContext, useContext, useState, type ReactNode } from 'react';
import en from '../locales/en.json';
import hu from '../locales/hu.json';

type Lang = 'en' | 'hu';
type Vars = Record<string, unknown> | undefined;
type TFunc = (key: string, vars?: Vars) => string;

const translations = { en, hu };

// Dot-path traversal into arbitrarily-shaped JSON translation trees isn't
// practically representable as a static type; kept dynamically typed on purpose.
function resolve(obj: unknown, key: string): unknown {
  return key.split('.').reduce((o: any, k) => o?.[k], obj);
}

function interpolate(str: string, vars: Vars): string {
  if (!vars) return str;
  return Object.entries(vars).reduce((s, [k, v]) => s.replaceAll(`{${k}}`, String(v)), str);
}

interface I18nContextValue {
  lang: Lang;
  t: TFunc;
  setLanguage: (l: Lang) => void;
}

const I18nContext = createContext<I18nContextValue | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLang] = useState<Lang>(() => {
    try {
      return (localStorage.getItem('lang') as Lang | null) || 'hu';
    } catch {
      return 'hu';
    }
  });

  const t: TFunc = (key, vars) => {
    const val = resolve(translations[lang], key) ?? resolve(translations.en, key) ?? key;
    return typeof val === 'string' ? interpolate(val, vars) : ((val as string | undefined) ?? key);
  };

  function setLanguage(l: Lang) {
    setLang(l);
    try { localStorage.setItem('lang', l); } catch {}
  }

  return (
    <I18nContext.Provider value={{ lang, t, setLanguage }}>
      {children}
    </I18nContext.Provider>
  );
}

export function useT(): I18nContextValue {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error('useT must be used within I18nProvider');
  return ctx;
}
