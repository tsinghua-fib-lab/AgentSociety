/**
 * i18n 国际化配置
 *
 * 使用 react-i18next 进行国际化支持
 * 默认语言：中文（可被宿主注入的 window.__AS_LANG__ 覆盖）
 */

import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import zhCN from './locales/zh-CN.json';
import enUS from './locales/en-US.json';

declare global {
  interface Window {
    __AS_LANG__?: string;
  }
}

const getDefaultLanguage = (): string => {
  const injected = typeof window !== 'undefined' ? window.__AS_LANG__ : undefined;
  if (injected === 'en-US' || injected === 'en') {
    return 'en-US';
  }
  if (injected === 'zh-CN' || injected === 'zh') {
    return 'zh-CN';
  }
  const urlParams = new URLSearchParams(window.location.search);
  const langParam = urlParams.get('lang');
  if (langParam === 'en-US' || langParam === 'en') {
    return 'en-US';
  }
  if (langParam === 'zh-CN' || langParam === 'zh') { return 'zh-CN'; }
  return document.documentElement.lang.startsWith('en') ? 'en-US' : 'zh-CN';
};

i18n
  .use(initReactI18next)
  .init({
    resources: {
      'zh-CN': {
        translation: zhCN,
      },
      'en-US': {
        translation: enUS,
      },
    },
    lng: getDefaultLanguage(), // 默认语言：中文
    fallbackLng: 'zh-CN', // 回退语言：中文
    interpolation: {
      escapeValue: false, // React 已经转义了
    },
  });

window.addEventListener('message', ({ data }) => {
  if (data?.type !== 'extensionLanguageChanged') { return; }
  const language = data.language;
  if (language === 'zh-CN' || language === 'en-US') {
    window.__AS_LANG__ = language;
    document.documentElement.lang = language;
    if (i18n.language !== language) { void i18n.changeLanguage(language); }
  }
});

export default i18n;

