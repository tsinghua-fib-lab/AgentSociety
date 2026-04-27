/**
 * 市场源配置面板组件
 */
import * as React from 'react';
import { Card, Input, Button, Typography, Empty } from 'antd';
import { DeleteOutlined } from '@ant-design/icons';
import type { SkillSourceConfig } from '../types';

const { Text } = Typography;

interface SourceItem extends SkillSourceConfig {
  // 兼容旧格式
}

interface SkillSourcesPanelProps {
  target: 'agent' | 'claudeCode';
  sources: SourceItem[];
  onSourcesChange: React.Dispatch<React.SetStateAction<SourceItem[]>>;
  onReset: () => void;
  onSave: (sources: SourceItem[]) => void;
  loading: boolean;
  panelBorder: string;
  editorBackground: string;
  editorForeground: string;
  t: (key: string) => string;
}

export const SkillSourcesPanel: React.FC<SkillSourcesPanelProps> = ({
  sources,
  onSourcesChange,
  onReset,
  onSave,
  loading,
  panelBorder,
  editorBackground,
  editorForeground,
  t,
}) => {
  const handleAddSource = () => {
    onSourcesChange([...sources, { owner: '', repo: '', branch: 'main', platform: 'github' }]);
  };

  const handleRemoveSource = (index: number) => {
    onSourcesChange(sources.filter((_, i) => i !== index));
  };

  const handleUpdateSource = (index: number, field: keyof SourceItem, value: string) => {
    const newSources = [...sources];
    (newSources[index] as Record<string, string>)[field] = value;
    onSourcesChange(newSources);
  };

  const handleSave = () => {
    onSave(sources.filter(s => s.owner.trim() && s.repo.trim()));
  };

  const selectStyle: React.CSSProperties = {
    marginTop: 4,
    width: '100%',
    height: 24,
    fontSize: 12,
    borderRadius: 4,
    border: `1px solid ${panelBorder}`,
    background: editorBackground,
    color: editorForeground,
  };

  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          {t('skillManagement.sourcesConfigHint')}
        </Text>
        <Button size="small" icon={<span>+</span>} onClick={handleAddSource}>
          {t('skillManagement.addSource')}
        </Button>
      </div>
      {sources.length === 0 ? (
        <Empty description={t('skillManagement.noSources')} style={{ padding: 20 }} />
      ) : (
        sources.map((source, index) => (
          <Card
            key={index}
            size="small"
            style={{ marginBottom: 8, borderColor: panelBorder }}
            styles={{ body: { padding: 12 } }}
          >
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <div style={{ flex: '1 1 120px', minWidth: 120 }}>
                <Text type="secondary" style={{ fontSize: 11 }}>{t('skillManagement.sourceOwner')}</Text>
                <Input
                  size="small"
                  value={source.owner}
                  onChange={(e) => handleUpdateSource(index, 'owner', e.target.value)}
                  placeholder="owner"
                  style={{ marginTop: 4 }}
                />
              </div>
              <div style={{ flex: '1 1 120px', minWidth: 120 }}>
                <Text type="secondary" style={{ fontSize: 11 }}>{t('skillManagement.sourceRepo')}</Text>
                <Input
                  size="small"
                  value={source.repo}
                  onChange={(e) => handleUpdateSource(index, 'repo', e.target.value)}
                  placeholder="repo"
                  style={{ marginTop: 4 }}
                />
              </div>
              <div style={{ flex: '0 0 80px' }}>
                <Text type="secondary" style={{ fontSize: 11 }}>{t('skillManagement.sourceBranch')}</Text>
                <Input
                  size="small"
                  value={source.branch || 'main'}
                  onChange={(e) => handleUpdateSource(index, 'branch', e.target.value)}
                  placeholder="main"
                  style={{ marginTop: 4 }}
                />
              </div>
              <div style={{ flex: '1 1 100px', minWidth: 100 }}>
                <Text type="secondary" style={{ fontSize: 11 }}>{t('skillManagement.sourcePath')}</Text>
                <Input
                  size="small"
                  value={source.skillsPath || ''}
                  onChange={(e) => handleUpdateSource(index, 'skillsPath', e.target.value)}
                  placeholder="skills"
                  style={{ marginTop: 4 }}
                />
              </div>
              <div style={{ flex: '0 0 90px' }}>
                <Text type="secondary" style={{ fontSize: 11 }}>{t('skillManagement.sourcePlatform')}</Text>
                <select
                  value={source.platform || 'github'}
                  onChange={(e) => handleUpdateSource(index, 'platform', e.target.value)}
                  style={selectStyle}
                >
                  <option value="github">GitHub</option>
                  <option value="gitlab">GitLab</option>
                  <option value="gitee">Gitee</option>
                </select>
              </div>
              <div style={{ flex: '0 0 auto', display: 'flex', alignItems: 'flex-end' }}>
                <Button
                  type="text"
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  onClick={() => handleRemoveSource(index)}
                />
              </div>
            </div>
            {source.platform && source.platform !== 'github' && (
              <div style={{ marginTop: 8 }}>
                <Text type="secondary" style={{ fontSize: 11 }}>{t('skillManagement.sourceBaseUrl')}</Text>
                <Input
                  size="small"
                  value={source.baseUrl || ''}
                  onChange={(e) => handleUpdateSource(index, 'baseUrl', e.target.value)}
                  placeholder={source.platform === 'gitlab' ? 'https://gitlab.com' : 'https://gitee.com'}
                  style={{ marginTop: 4 }}
                />
              </div>
            )}
          </Card>
        ))
      )}
      <div style={{ marginTop: 12, display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        <Button size="small" onClick={onReset} loading={loading}>
          {t('skillManagement.resetSources')}
        </Button>
        <Button type="primary" size="small" onClick={handleSave} loading={loading}>
          {t('skillManagement.saveSources')}
        </Button>
      </div>
    </div>
  );
};
