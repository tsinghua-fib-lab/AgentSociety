import * as React from 'react';
import { Collapse, Form, Input, InputNumber, Select, Typography } from 'antd';
import { useTranslation } from 'react-i18next';
import type { ProviderUsageConfig } from '../../shared/providerUsage';

export function ProviderUsageSettings({ value, onChange, allowCustom }: {
  value?: ProviderUsageConfig;
  onChange: (value: ProviderUsageConfig) => void;
  allowCustom: boolean;
}) {
  const { t } = useTranslation();
  const patch = (partial: Partial<ProviderUsageConfig>) => onChange({ mode: 'auto', ...value, ...partial });
  return <Collapse size="small" items={[{
    key: 'usage', label: t('claudeCodeConfig.accountUsage.settings'), children: <>
      <Select
        aria-label={t('claudeCodeConfig.accountUsage.mode')} value={value?.mode ?? 'auto'} style={{ width: '100%', marginBottom: 8 }}
        options={(['auto', 'off', 'custom'] as const).filter((mode) => mode !== 'custom' || allowCustom).map((mode) => ({ value: mode, label: t(`claudeCodeConfig.accountUsage.mode_${mode}`) }))}
        onChange={(mode) => patch({ mode })}
      />
      <Typography.Text type="secondary" style={{ display: 'block', fontSize: 12, marginBottom: 8 }}>{t('claudeCodeConfig.accountUsage.settingsHint')}</Typography.Text>
      {value?.mode === 'custom' ? <Form layout="vertical" component="div" size="small">
        {([
          ['path', '/user/balance'], ['remainingPath', 'data.balance'], ['usedPath', 'data.used'], ['totalPath', 'data.total'], ['unit', 'CNY'],
        ] as const).map(([field, placeholder]) => <Form.Item key={field} label={t(`claudeCodeConfig.accountUsage.field_${field}`)} required={field === 'path' || field === 'remainingPath'} style={{ marginBottom: 10 }}>
          <Input aria-label={t(`claudeCodeConfig.accountUsage.field_${field}`)} value={value[field] ?? ''} placeholder={placeholder} onChange={(event) => patch({ [field]: event.target.value })} />
        </Form.Item>)}
        <Form.Item label={t('claudeCodeConfig.accountUsage.field_divisor')} style={{ marginBottom: 0 }}>
          <InputNumber aria-label={t('claudeCodeConfig.accountUsage.field_divisor')} min={0.000001} value={value.divisor ?? 1} onChange={(divisor) => patch({ divisor: divisor ?? 1 })} style={{ width: '100%' }} />
        </Form.Item>
      </Form> : null}
    </>,
  }]} />;
}
