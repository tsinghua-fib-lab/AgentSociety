import * as React from 'react';
import { Popover, Space, Tag, Typography } from 'antd';
import type { VscodeThemePalette } from '../../theme';
import { ListCard } from './ListCard';
import { iconBadgeStyle } from '../uiTokens';

const { Paragraph, Title } = Typography;

export type SkillEntryCardProps = {
  palette: VscodeThemePalette;
  title: React.ReactNode;
  description?: React.ReactNode;
  tags?: React.ReactNode;
  icon?: React.ReactNode;
  accent?: string;
  actions?: React.ReactNode;
  children?: React.ReactNode;
  hoverable?: boolean;
  style?: React.CSSProperties;
};

export function versionTag(version?: string): React.ReactNode {
  const raw = (version ?? '').trim();
  if (!raw) {
    return null;
  }
  const label = raw.startsWith('v') ? raw : `v${raw}`;
  return (
    <Tag style={{ margin: 0, fontSize: 11, lineHeight: '18px' }}>
      {label}
    </Tag>
  );
}

export function SkillEntryCard({
  palette,
  title,
  description,
  tags,
  icon,
  accent,
  actions,
  children,
  hoverable = true,
  style,
}: SkillEntryCardProps) {
  const badgeAccent = accent ?? palette.linkForeground;

  return (
    <ListCard
      palette={palette}
      hoverable={hoverable}
      accent={accent}
      style={{ minWidth: 0, alignSelf: 'start', marginBottom: 0, ...style }}
    >
      <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}>
        {icon ? <span style={iconBadgeStyle(badgeAccent)}>{icon}</span> : null}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              justifyContent: 'space-between',
              gap: 8,
            }}
          >
            <div style={{ minWidth: 0, width: '100%' }}>
              <Title
                level={5}
                title={typeof title === 'string' ? title : undefined}
                style={{ margin: 0, fontSize: 15, lineHeight: '22px', height: 22, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
              >
                {title}
              </Title>
              <div style={{ height: 26, marginTop: 6 }}>
                {tags ? <Popover classNames={{ root: 'as-skill-label-popover' }} content={<Space size={[4, 4]} wrap style={{ maxWidth: 'min(320px, calc(100vw - 64px))' }}>{tags}</Space>} trigger={['hover', 'focus']}>
                  <div className="as-skill-labels" tabIndex={0} style={{ maxHeight: 24, overflow: 'hidden' }}>
                    <Space size={[4, 4]} wrap>{tags}</Space>
                  </div>
                </Popover> : null}
              </div>
            </div>
          </div>
            <Paragraph
              type="secondary"
              ellipsis={{ rows: 3, tooltip: typeof description === 'string' ? description : undefined }}
              style={{ margin: '10px 0 0', minHeight: 60, fontSize: 13, lineHeight: '20px', overflowWrap: 'anywhere' }}
            >
              {description}
            </Paragraph>
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', minHeight: 28, marginTop: 10 }}>
        {actions ? <Space wrap size={4} style={{ justifyContent: 'flex-end', minWidth: 0 }}>{actions}</Space> : null}
      </div>
      {children ? <div style={{ marginTop: 8 }}>{children}</div> : null}
    </ListCard>
  );
}
