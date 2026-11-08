import * as React from 'react';
import { Space, Tooltip, Typography } from 'antd';
import { QuestionCircleOutlined } from '@ant-design/icons';
import type { VscodeThemePalette } from '../../theme';
import { SKILL_UI, sectionShellStyle } from '../uiTokens';

const { Text } = Typography;

export type PageSectionProps = {
  palette: VscodeThemePalette;
  icon?: React.ReactNode;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  help?: string;
  extra?: React.ReactNode;
  children: React.ReactNode;
  style?: React.CSSProperties;
};

export function PageSection({
  palette,
  icon,
  title,
  subtitle,
  help,
  extra,
  children,
  style,
}: PageSectionProps) {
  return (
    <section style={{ ...sectionShellStyle(palette), ...style }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: SKILL_UI.space.md,
          marginBottom: SKILL_UI.space.md,
          flexWrap: 'wrap',
        }}
      >
        <div style={{ minWidth: 0, flex: '1 1 240px' }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
            <Text strong style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 14 }}>
              {icon}
              {title}
            </Text>
            {help ? (
              <Tooltip title={help}>
                <QuestionCircleOutlined style={{ fontSize: 12, color: palette.descriptionForeground }} />
              </Tooltip>
            ) : null}
          </div>
          {subtitle ? (
            <Text
              type="secondary"
              style={{ display: 'block', fontSize: 12, marginTop: 4, lineHeight: 1.55 }}
            >
              {subtitle}
            </Text>
          ) : null}
        </div>
        {extra ? <Space wrap size={SKILL_UI.space.sm}>{extra}</Space> : null}
      </div>
      {children}
    </section>
  );
}
