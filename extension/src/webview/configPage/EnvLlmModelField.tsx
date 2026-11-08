import * as React from 'react';
import { Button, Space, Tag, Typography } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import type { TFunction } from 'i18next';
import type { ClaudeModelOption } from './claudeCodeTypes';
import { ClaudeModelSelect } from './ClaudeModelSelect';

const { Text } = Typography;

type Props = {
  id?: string;
  t: TFunction;
  value?: string;
  onChange?: (value: string) => void;
  models: ClaudeModelOption[];
  loading: boolean;
  error: string | null;
  canFetch: boolean;
  onFetch: () => void;
  placeholder: string;
};

export function EnvLlmModelField({
  id,
  t,
  value,
  onChange,
  models,
  loading,
  error,
  canFetch,
  onFetch,
  placeholder,
}: Props) {
  return (
    <Space direction="vertical" style={{ width: '100%' }} size={6}>
      <Space.Compact style={{ width: '100%' }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <ClaudeModelSelect
            id={id}
            value={value}
            onChange={onChange}
            models={models}
            placeholder={placeholder}
            loading={loading}
          />
        </div>
        <Button
          icon={<ReloadOutlined />}
          loading={loading}
          disabled={!canFetch}
          onClick={onFetch}
        >
          {t('configPage.llm.fetchModels')}
        </Button>
      </Space.Compact>
      <Space size={6} wrap>
        {error ? <Tag color="error">{error}</Tag> : null}
        {!error && models.length > 0 ? (
          <Tag color="success">{t('configPage.llm.modelsCount', { count: models.length })}</Tag>
        ) : null}
        {!error && models.length === 0 && !loading ? (
          <Text type="secondary" style={{ fontSize: 11 }}>{t('configPage.llm.fetchModelsHint')}</Text>
        ) : null}
      </Space>
    </Space>
  );
}
