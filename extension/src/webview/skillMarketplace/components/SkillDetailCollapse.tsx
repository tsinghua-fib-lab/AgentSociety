/**
 * 技能详情折叠面板组件
 */
import * as React from 'react';
import { Collapse, Spin } from 'antd';

export interface SkillDetailCollapseProps {
  panelLabel: string;
  onPanelOpen?: () => void;
  loading: boolean;
  borderColor: string;
  children: React.ReactNode;
}

export const SkillDetailCollapse: React.FC<SkillDetailCollapseProps> = ({
  panelLabel,
  onPanelOpen,
  loading,
  borderColor,
  children,
}) => (
  <Collapse
    ghost
    size="small"
    style={{ marginTop: 8, borderTop: `1px solid ${borderColor}`, paddingTop: 8 }}
    destroyInactivePanel
    onChange={(keys) => {
      const arr = Array.isArray(keys) ? keys : keys != null ? [keys as string] : [];
      if (arr.includes('detail')) {
        onPanelOpen?.();
      }
    }}
    items={[
      {
        key: 'detail',
        label: <span style={{ fontSize: 12 }}>{panelLabel}</span>,
        children: loading ? (
          <div style={{ padding: 8 }}>
            <Spin size="small" />
          </div>
        ) : (
          children
        ),
      },
    ]}
  />
);
