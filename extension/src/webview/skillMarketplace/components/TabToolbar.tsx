import * as React from 'react';
import { Space } from 'antd';
import { SKILL_UI } from '../uiTokens';

export type TabToolbarProps = {
  left: React.ReactNode;
  right?: React.ReactNode;
};

export function TabToolbar({ left, right }: TabToolbarProps) {
  return (
    <div
      style={{
        marginBottom: SKILL_UI.space.lg,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: SKILL_UI.space.md,
      }}
    >
      <div style={{ flex: '1 1 220px', minWidth: 0 }}>{left}</div>
      {right ? (
        <Space wrap size="small" style={{ flex: '0 1 auto', maxWidth: '100%', justifyContent: 'flex-end' }}>
          {right}
        </Space>
      ) : null}
    </div>
  );
}
