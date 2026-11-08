import * as React from 'react';
import { Card } from 'antd';
import type { VscodeThemePalette } from '../../theme';
import { SKILL_UI, surfaceCardStyle } from '../uiTokens';

export type ListCardProps = {
  palette: VscodeThemePalette;
  children: React.ReactNode;
  hoverable?: boolean;
  accent?: string;
  style?: React.CSSProperties;
  bodyStyle?: React.CSSProperties;
  onClick?: () => void;
};

export function ListCard({
  palette,
  children,
  hoverable,
  accent,
  style,
  bodyStyle,
  onClick,
}: ListCardProps) {
  return (
    <Card
      hoverable={hoverable}
      onClick={onClick}
      style={{
        ...surfaceCardStyle(palette, { accent }),
        marginBottom: SKILL_UI.space.md,
        ...style,
      }}
      styles={{ body: { padding: '14px 16px', ...bodyStyle } }}
    >
      {children}
    </Card>
  );
}
