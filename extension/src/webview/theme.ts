import * as React from 'react';
import { theme } from 'antd';
import type { ThemeConfig } from 'antd';
import './webview.css';

export const UI = {
  radius: { control: 8, card: 12, panel: 16 },
  space: { xs: 4, sm: 8, md: 12, lg: 16, xl: 24 },
} as const;

export interface VscodeThemePalette {
  editorBackground: string;
  editorForeground: string;
  descriptionForeground: string;
  panelBorder: string;
  inputBackground: string;
  inputForeground: string;
  inputBorder: string;
  buttonBackground: string;
  buttonForeground: string;
  buttonHoverBackground: string;
  linkForeground: string;
  errorForeground: string;
  warningForeground: string;
  successForeground: string;
  listHoverBackground: string;
  inactiveSelectionBackground: string;
  activeSelectionBackground: string;
  activeSelectionForeground: string;
  badgeBackground: string;
  badgeForeground: string;
  focusBorder: string;
  surfaceBackground: string;
  surfaceMuted: string;
  codeBlockBackground: string;
}

interface VscodeThemeState {
  isDark: boolean;
  isHighContrast: boolean;
  reduceMotion: boolean;
  palette: VscodeThemePalette;
}

const FONT_FAMILY = `var(--vscode-font-family, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif)`;

const FALLBACK_LIGHT = {
  editorBackground: '#ffffff',
  editorForeground: '#1f1f1f',
  descriptionForeground: '#666666',
  panelBorder: '#d9d9d9',
  inputBackground: '#ffffff',
  inputForeground: '#1f1f1f',
  inputBorder: '#d9d9d9',
  buttonBackground: '#1677ff',
  buttonForeground: '#ffffff',
  buttonHoverBackground: '#4096ff',
  linkForeground: '#1677ff',
  errorForeground: '#ff4d4f',
  warningForeground: '#faad14',
  successForeground: '#52c41a',
  listHoverBackground: 'rgba(0, 0, 0, 0.04)',
  inactiveSelectionBackground: 'rgba(0, 0, 0, 0.06)',
  activeSelectionBackground: 'rgba(22, 119, 255, 0.12)',
  activeSelectionForeground: '#1f1f1f',
  badgeBackground: '#d9d9d9',
  badgeForeground: '#1f1f1f',
  focusBorder: '#1677ff',
  surfaceBackground: '#f7f7f7',
  surfaceMuted: '#fafafa',
  codeBlockBackground: '#f5f5f5',
};

const FALLBACK_DARK = {
  editorBackground: '#1e1e1e',
  editorForeground: '#d4d4d4',
  descriptionForeground: '#9d9d9d',
  panelBorder: '#3c3c3c',
  inputBackground: '#252526',
  inputForeground: '#d4d4d4',
  inputBorder: '#3c3c3c',
  buttonBackground: '#1677ff',
  buttonForeground: '#ffffff',
  buttonHoverBackground: '#4096ff',
  linkForeground: '#4da3ff',
  errorForeground: '#ff7875',
  warningForeground: '#ffc53d',
  successForeground: '#73d13d',
  listHoverBackground: 'rgba(255, 255, 255, 0.06)',
  inactiveSelectionBackground: 'rgba(255, 255, 255, 0.08)',
  activeSelectionBackground: 'rgba(22, 119, 255, 0.22)',
  activeSelectionForeground: '#ffffff',
  badgeBackground: '#4d4d4d',
  badgeForeground: '#ffffff',
  focusBorder: '#4096ff',
  surfaceBackground: '#252526',
  surfaceMuted: '#2d2d30',
  codeBlockBackground: '#1f1f1f',
};

const readCssVar = (styles: CSSStyleDeclaration, name: string, fallback: string): string => {
  const value = styles.getPropertyValue(name).trim();
  return value || fallback;
};

const readThemeState = (): VscodeThemeState => {
  const classList = document.body?.classList;
  const hasExplicitThemeClass = Boolean(
    classList?.contains('vscode-light') ||
    classList?.contains('vscode-dark') ||
    classList?.contains('vscode-high-contrast') ||
    classList?.contains('vscode-high-contrast-light')
  );
  const prefersDark = typeof window.matchMedia === 'function'
    ? window.matchMedia('(prefers-color-scheme: dark)').matches
    : false;
  const isDark = Boolean(
    classList?.contains('vscode-dark') ||
    classList?.contains('vscode-high-contrast') ||
    (!hasExplicitThemeClass && prefersDark)
  );
  const isHighContrast = Boolean(
    classList?.contains('vscode-high-contrast') ||
    classList?.contains('vscode-high-contrast-light')
  );
  const fallbacks = isDark ? FALLBACK_DARK : FALLBACK_LIGHT;
  const styles = getComputedStyle(document.body ?? document.documentElement);

  return {
    isDark,
    isHighContrast,
    reduceMotion: window.matchMedia('(prefers-reduced-motion: reduce)').matches,
    palette: {
      editorBackground: readCssVar(styles, '--vscode-editor-background', fallbacks.editorBackground),
      editorForeground: readCssVar(styles, '--vscode-editor-foreground', fallbacks.editorForeground),
      descriptionForeground: readCssVar(styles, '--vscode-descriptionForeground', fallbacks.descriptionForeground),
      panelBorder: isHighContrast
        ? readCssVar(styles, '--vscode-contrastBorder', fallbacks.editorForeground)
        : readCssVar(styles, '--vscode-panel-border', fallbacks.panelBorder),
      inputBackground: readCssVar(styles, '--vscode-input-background', fallbacks.inputBackground),
      inputForeground: readCssVar(styles, '--vscode-input-foreground', fallbacks.inputForeground),
      inputBorder: readCssVar(styles, '--vscode-input-border', fallbacks.inputBorder),
      buttonBackground: readCssVar(styles, '--vscode-button-background', fallbacks.buttonBackground),
      buttonForeground: readCssVar(styles, '--vscode-button-foreground', fallbacks.buttonForeground),
      buttonHoverBackground: readCssVar(styles, '--vscode-button-hoverBackground', fallbacks.buttonHoverBackground),
      linkForeground: readCssVar(styles, '--vscode-textLink-foreground', fallbacks.linkForeground),
      errorForeground: readCssVar(styles, '--vscode-errorForeground', fallbacks.errorForeground),
      warningForeground: readCssVar(styles, '--vscode-editorWarning-foreground', fallbacks.warningForeground),
      successForeground: readCssVar(styles, '--vscode-testing-iconPassed', fallbacks.successForeground),
      listHoverBackground: readCssVar(styles, '--vscode-list-hoverBackground', fallbacks.listHoverBackground),
      inactiveSelectionBackground: readCssVar(
        styles,
        '--vscode-editor-inactiveSelectionBackground',
        fallbacks.inactiveSelectionBackground
      ),
      activeSelectionBackground: readCssVar(
        styles,
        '--vscode-list-activeSelectionBackground',
        fallbacks.activeSelectionBackground
      ),
      activeSelectionForeground: readCssVar(
        styles,
        '--vscode-list-activeSelectionForeground',
        fallbacks.activeSelectionForeground
      ),
      badgeBackground: readCssVar(styles, '--vscode-badge-background', fallbacks.badgeBackground),
      badgeForeground: readCssVar(styles, '--vscode-badge-foreground', fallbacks.badgeForeground),
      focusBorder: readCssVar(styles, '--vscode-focusBorder', fallbacks.focusBorder),
      surfaceBackground: readCssVar(styles, '--vscode-sideBar-background', fallbacks.surfaceBackground),
      surfaceMuted: readCssVar(styles, '--vscode-editorWidget-background', fallbacks.surfaceMuted),
      codeBlockBackground: readCssVar(
        styles,
        '--vscode-textCodeBlock-background',
        fallbacks.codeBlockBackground
      ),
    },
  };
};

export const useVscodeTheme = (): VscodeThemeState & { themeConfig: ThemeConfig } => {
  const [themeState, setThemeState] = React.useState<VscodeThemeState>(() => readThemeState());

  React.useEffect(() => {
    let frameId = 0;

    const scheduleUpdate = () => {
      if (frameId) {
        cancelAnimationFrame(frameId);
      }
      frameId = requestAnimationFrame(() => {
        setThemeState(readThemeState());
      });
    };

    scheduleUpdate();

    const observer = new MutationObserver(scheduleUpdate);
    if (document.body) {
      observer.observe(document.body, {
        attributes: true,
        attributeFilter: ['class', 'style'],
      });
    }

    const mediaQueries = ['(prefers-color-scheme: dark)', '(prefers-reduced-motion: reduce)']
      .map((query) => window.matchMedia(query));
    mediaQueries.forEach((query) => query.addEventListener('change', scheduleUpdate));

    window.addEventListener('focus', scheduleUpdate);

    return () => {
      observer.disconnect();
      if (frameId) {
        cancelAnimationFrame(frameId);
      }
      mediaQueries.forEach((query) => query.removeEventListener('change', scheduleUpdate));
      window.removeEventListener('focus', scheduleUpdate);
    };
  }, []);

  const { isDark, isHighContrast, reduceMotion, palette } = themeState;

  const themeConfig = React.useMemo<ThemeConfig>(
    () => ({
      algorithm: isDark ? theme.darkAlgorithm : theme.defaultAlgorithm,
      token: {
        colorPrimary: palette.buttonBackground,
        colorInfo: palette.linkForeground,
        colorSuccess: palette.successForeground,
        colorWarning: palette.warningForeground,
        colorError: palette.errorForeground,
        colorTextBase: palette.editorForeground,
        colorText: palette.editorForeground,
        colorTextHeading: palette.editorForeground,
        colorTextSecondary: palette.descriptionForeground,
        colorTextDescription: palette.descriptionForeground,
        colorTextTertiary: palette.descriptionForeground,
        colorBgBase: palette.editorBackground,
        colorBgContainer: isHighContrast ? palette.editorBackground : palette.inputBackground,
        colorBgElevated: isHighContrast ? palette.editorBackground : palette.surfaceMuted,
        colorBorder: isHighContrast ? palette.focusBorder : palette.panelBorder,
        colorBorderSecondary: isHighContrast ? palette.focusBorder : palette.panelBorder,
        colorFillSecondary: palette.listHoverBackground,
        colorFillTertiary: palette.inactiveSelectionBackground,
        controlItemBgHover: palette.listHoverBackground,
        controlItemBgActive: palette.activeSelectionBackground,
        controlItemBgActiveHover: palette.activeSelectionBackground,
        borderRadius: UI.radius.control,
        borderRadiusSM: UI.radius.control,
        borderRadiusLG: UI.radius.panel,
        controlHeight: 34,
        controlHeightSM: 28,
        controlHeightLG: 40,
        fontSize: 13,
        fontSizeSM: 12,
        lineHeight: 1.6,
        fontFamily: FONT_FAMILY,
        motion: !reduceMotion,
        ...(isHighContrast ? { boxShadow: 'none', boxShadowSecondary: 'none' } : {}),
      },
      components: {
        Button: { primaryColor: palette.buttonForeground, defaultShadow: 'none', primaryShadow: 'none', dangerShadow: 'none', paddingInline: 14, paddingInlineSM: 10 },
        Card: { borderRadiusLG: UI.radius.panel, headerFontSize: 14, paddingLG: 20 },
        Modal: { borderRadiusLG: UI.radius.panel },
        Alert: { borderRadiusLG: UI.radius.card },
        Collapse: { borderRadiusLG: UI.radius.card, headerPadding: '12px 16px' },
        Tabs: { horizontalItemGutter: 24, titleFontSize: 13 },
        Table: { borderRadiusLG: UI.radius.card, headerBg: palette.surfaceBackground },
      },
    }),
    [isDark, isHighContrast, reduceMotion, palette]
  );

  return {
    ...themeState,
    themeConfig,
  };
};
