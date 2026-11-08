import type { CSSProperties } from 'react';
import { UI, type VscodeThemePalette } from '../theme';

export function panelCardStyle(palette: VscodeThemePalette): CSSProperties {
  return {
    marginBottom: 16,
    borderRadius: UI.radius.panel,
    border: `1px solid ${palette.panelBorder}`,
    background: palette.surfaceMuted,
  };
}

export function advancedPanelInnerStyle(palette: VscodeThemePalette): CSSProperties {
  return {
    padding: '16px 18px 8px',
    borderRadius: UI.radius.card,
    background: palette.surfaceBackground,
    border: `1px solid ${palette.panelBorder}`,
  };
}

export const tabBodyStyle: CSSProperties = {
  paddingTop: 4,
  paddingBottom: 4,
};
