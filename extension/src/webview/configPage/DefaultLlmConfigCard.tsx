import * as React from 'react';
import { Alert, Card, Form, Input, Select, Space, Tag, Tooltip } from 'antd';
import { KeyOutlined, QuestionCircleOutlined } from '@ant-design/icons';
import type { TFunction } from 'i18next';
import type { FormInstance } from 'antd';
import type { VscodeThemePalette } from '../theme';
import type { ClaudeModelOption } from './claudeCodeTypes';
import type { ConfigValues, ValidationState } from './types';
import { panelCardStyle } from './configPageStyles';
import { ValidationAction } from './ValidationAction';
import { EnvLlmModelField } from './EnvLlmModelField';
import { ThinkingSelect, LlmApiTypeField } from './ThinkingSelect';
import { SIM_LLM_PRESETS, matchSimLlmPreset } from './simLlmPresets';

type Props = {
  t: TFunction;
  palette: VscodeThemePalette;
  isDark: boolean;
  form: FormInstance<ConfigValues>;
  baseUrl: string;
  apiKey: string;
  models: ClaudeModelOption[];
  modelsLoading: boolean;
  modelsError: string | null;
  onFetchModels: () => void;
  validationState: ValidationState;
  validateDisabledReason: string | null;
  onValidate: () => void;
  showIntro?: boolean;
};

export function DefaultLlmConfigCard({
  t,
  palette,
  isDark,
  form,
  baseUrl,
  apiKey,
  models,
  modelsLoading,
  modelsError,
  onFetchModels,
  validationState,
  validateDisabledReason,
  onValidate,
  showIntro = true,
}: Props) {
  const safeBaseUrl = baseUrl ?? '';
  const safeApiKey = apiKey ?? '';
  const apiType = Form.useWatch('llmApiType', form) || 'openai';
  const presetId = matchSimLlmPreset(safeBaseUrl);
  const selectedPreset = SIM_LLM_PRESETS.find((preset) => preset.id === presetId);
  const canFetch = Boolean(safeBaseUrl.trim() && safeApiKey.trim());
  const fetchFingerprintRef = React.useRef('');
  const connectionFingerprint = `${safeBaseUrl.trim()}::${safeApiKey}::${apiType}`;

  React.useEffect(() => {
    const fingerprint = `${safeBaseUrl.trim()}::${safeApiKey}::${apiType}`;
    if (!canFetch) {
      if (fetchFingerprintRef.current !== fingerprint) {
        fetchFingerprintRef.current = fingerprint;
        onFetchModels();
      }
      return;
    }
    if (fetchFingerprintRef.current === fingerprint) {
      return;
    }
    const timer = window.setTimeout(() => {
      fetchFingerprintRef.current = fingerprint;
      onFetchModels();
    }, 800);
    return () => window.clearTimeout(timer);
  }, [safeApiKey, safeBaseUrl, apiType, canFetch, onFetchModels]);

  const handlePresetChange = (id: string) => {
    fetchFingerprintRef.current = '';
    if (id === 'custom') {
      form.setFieldsValue({ llmApiBase: '', llmApiKey: '', llmModel: '' });
      return;
    }
    const preset = SIM_LLM_PRESETS.find((p) => p.id === id);
    if (!preset) {
      return;
    }
    const patch: Partial<ConfigValues> = {
      llmApiBase: preset.baseUrl,
      llmModel: presetId === preset.id ? form.getFieldValue('llmModel') : '',
    };
    if (matchSimLlmPreset(safeBaseUrl) !== preset.id) { patch.llmApiKey = ''; }
    form.setFieldsValue(patch);
  };

  return (
    <Card
      title={(
        <Space>
          <KeyOutlined style={{ color: palette.errorForeground }} />
          <span>{t('configPage.llm.cardTitle')}</span>
          {showIntro ? <Tooltip title={t('configPage.pageTabs.simulationIntroBody')}><QuestionCircleOutlined tabIndex={0} /></Tooltip> : null}
          <Tag color="red" style={{ marginLeft: 4 }}>{t('configPage.llm.requiredTag')}</Tag>
        </Space>
      )}
      style={panelCardStyle(palette)}
      styles={{ body: { padding: '16px 20px' } }}
    >
      <Form.Item label={t('configPage.llm.presetLabel')} style={{ marginBottom: 12 }}>
        <Select
          value={presetId}
          options={SIM_LLM_PRESETS.map((p) => ({
            value: p.id,
            label: t(p.labelKey),
          }))}
          onChange={handlePresetChange}
        />
      </Form.Item>
      {selectedPreset?.hintKey ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12, fontSize: 12 }}
          message={t(selectedPreset.hintKey)}
        />
      ) : null}
      <Form.Item name="llmApiBase" label={t('configPage.llm.apiBase')}>
        <Input placeholder={t('configPage.llm.apiBasePlaceholder')} />
      </Form.Item>
      <Form.Item
        name="llmApiKey"
        label={t('configPage.llm.apiKeyRequired')}
        rules={[{ required: true, message: t('configPage.notifications.apiKeyMissing') }]}
        tooltip={t('configPage.llm.apiKeyRequiredHint')}
      >
        <Input.Password placeholder={t('configPage.llm.apiKeyPlaceholder')} autoComplete="off" />
      </Form.Item>
      <Form.Item name="llmModel" label={t('configPage.llm.modelName')}
        rules={[{ required: true, whitespace: true, message: t('configPage.llm.modelRequired') }]}>
        <EnvLlmModelField
          t={t}
          models={fetchFingerprintRef.current === connectionFingerprint && canFetch ? models : []}
          loading={modelsLoading}
          error={modelsError}
          canFetch={canFetch}
          onFetch={() => {
            fetchFingerprintRef.current = connectionFingerprint;
            onFetchModels();
          }}
          placeholder={t('configPage.llm.modelPlaceholder')}
        />
      </Form.Item>
      <Form.Item
        name="llmThinking"
        label={t('configPage.llm.thinking')}
        tooltip={t('configPage.llm.thinkingHint')}
      >
        <ThinkingSelect t={t} scope="default" />
      </Form.Item>
      <LlmApiTypeField t={t} scope="default" />
      <ValidationAction
        t={t}
        palette={palette}
        state={validationState}
        disabledReason={validateDisabledReason}
        onValidate={onValidate}
      />
    </Card>
  );
}
