/**
 * 更新差异预览弹窗组件
 */
import * as React from 'react';
import { Modal, Tag, Spin, Typography } from 'antd';
import type { MarketplaceSkill, SkillUpdateDiff, SkillFileDiff } from '../types';

const { Text } = Typography;

interface UpdateDiffModalProps {
  open: boolean;
  skill?: MarketplaceSkill;
  diff?: SkillUpdateDiff;
  panelBorder: string;
  codeBlockBackground: string;
  editorForeground: string;
  onConfirm: (skill: MarketplaceSkill) => void;
  onCancel: () => void;
  t: (key: string, params?: Record<string, unknown>) => string;
}

const FileDiffItem: React.FC<{
  fileDiff: SkillFileDiff;
  codeBlockBackground: string;
  panelBorder: string;
  editorForeground: string;
}> = ({ fileDiff, codeBlockBackground, panelBorder, editorForeground }) => (
  <div style={{ marginBottom: 14 }}>
    <Text strong style={{ fontSize: 12 }}>{fileDiff.path}</Text>
    <Tag
      style={{ marginLeft: 8 }}
      color={fileDiff.status === 'added' ? 'green' : fileDiff.status === 'deleted' ? 'red' : 'blue'}
    >
      {fileDiff.status}
    </Tag>
    {(fileDiff.hunks || []).map((h, idx) => (
      <pre
        key={idx}
        style={{
          marginTop: 8,
          marginBottom: 0,
          padding: '10px 12px',
          background: codeBlockBackground,
          border: `1px solid ${panelBorder}`,
          borderRadius: 8,
          fontSize: 11,
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          color: editorForeground,
        }}
      >
        {h.lines?.join('\n') || ''}
      </pre>
    ))}
  </div>
);

export const UpdateDiffModal: React.FC<UpdateDiffModalProps> = ({
  open,
  skill,
  diff,
  panelBorder,
  codeBlockBackground,
  editorForeground,
  onConfirm,
  onCancel,
  t,
}) => {
  const title = t('skillManagement.updateDiffTitle', {
    name: skill?.name || diff?.skillName || '',
    from: diff?.localVersion || skill?.installedVersion || '',
    to: diff?.remoteVersion || skill?.version || '',
  });

  return (
    <Modal
      open={open}
      title={title}
      width={920}
      okText={t('skillManagement.confirmUpdate')}
      cancelText={t('skillManagement.cancel')}
      onCancel={onCancel}
      onOk={() => {
        if (skill) {
          onConfirm(skill);
        }
      }}
      okButtonProps={{ disabled: !skill }}
    >
      {!diff ? (
        <div style={{ padding: 16, textAlign: 'center' }}>
          <Spin />
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, fontSize: 12 }}>
            <Tag color="green">{t('skillManagement.diffAdded', { count: diff.filesAdded.length })}</Tag>
            <Tag color="red">{t('skillManagement.diffDeleted', { count: diff.filesDeleted.length })}</Tag>
            <Tag color="blue">{t('skillManagement.diffModified', { count: diff.filesModified.length })}</Tag>
          </div>
          <div style={{ maxHeight: 460, overflow: 'auto', border: `1px solid ${panelBorder}`, borderRadius: 10 }}>
            <div style={{ padding: 12 }}>
              {(diff.fileDiffs || []).map((f) => (
                <FileDiffItem
                  key={f.path}
                  fileDiff={f}
                  codeBlockBackground={codeBlockBackground}
                  panelBorder={panelBorder}
                  editorForeground={editorForeground}
                />
              ))}
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
};
