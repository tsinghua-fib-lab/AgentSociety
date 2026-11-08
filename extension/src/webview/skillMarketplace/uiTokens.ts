import type { CSSProperties } from 'react';
import { UI, type VscodeThemePalette } from '../theme';

/** Shared layout tokens for the skill management webview. */
export const SKILL_UI = {
  radius: {
    sm: UI.radius.control,
    md: UI.radius.card,
    lg: UI.radius.panel,
  },
  space: {
    xs: 6,
    sm: UI.radius.control,
    md: UI.radius.card,
    lg: UI.radius.panel,
    xl: 20,
  },
  maxWidth: 1180,
  cardMinWidth: 340,
} as const;

export function surfaceCardStyle(palette: VscodeThemePalette, opts?: {
  accent?: string;
  muted?: boolean;
}): CSSProperties {
  return {
    background: opts?.muted ? palette.surfaceBackground : palette.surfaceMuted,
    border: `1px solid ${palette.panelBorder}`,
    borderLeft: opts?.accent ? `3px solid ${opts.accent}` : undefined,
    borderRadius: SKILL_UI.radius.md,
  };
}

export function sectionShellStyle(palette: VscodeThemePalette): CSSProperties {
  return {
    marginBottom: SKILL_UI.space.xl,
    padding: `${SKILL_UI.space.lg}px ${SKILL_UI.space.lg}px ${SKILL_UI.space.md}px`,
    borderRadius: SKILL_UI.radius.md,
    border: `1px solid ${palette.panelBorder}`,
    background: palette.surfaceMuted,
  };
}

export function heroShellStyle(palette: VscodeThemePalette): CSSProperties {
  return {
    marginBottom: SKILL_UI.space.xl,
    padding: '22px 24px',
    borderRadius: SKILL_UI.radius.lg,
    border: `1px solid ${palette.panelBorder}`,
    background: palette.surfaceMuted,
  };
}

export function iconBadgeStyle(accent: string): CSSProperties {
  return {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: 40,
    height: 40,
    borderRadius: SKILL_UI.radius.md,
    flexShrink: 0,
    background: `color-mix(in srgb, ${accent} 12%, transparent)`,
    color: accent,
  };
}

export function skillGridStyle(): CSSProperties {
  return {
    display: 'grid',
    gridTemplateColumns: `repeat(auto-fill, minmax(min(100%, ${SKILL_UI.cardMinWidth}px), 1fr))`,
    gap: SKILL_UI.space.md,
  };
}
