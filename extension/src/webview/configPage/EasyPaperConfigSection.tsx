import * as React from 'react';
import { Alert, Button, Form, Input, Select, Switch, Typography } from 'antd';
import { CopyOutlined, SaveOutlined } from '@ant-design/icons';
import type { FormInstance } from 'antd';
import type { TFunction } from 'i18next';
import type { VscodeThemePalette } from '../theme';
import type { EasyPaperConfigValues } from './types';
import type { ClaudeModelOption } from './claudeCodeTypes';
import { tabBodyStyle } from './configPageStyles';
import { EnvLlmModelField } from './EnvLlmModelField';
import { ENV_LLM_SLOT } from './envLlmSlots';
import { SIM_LLM_PRESETS, matchSimLlmPreset } from './simLlmPresets';

const { Text } = Typography;

export interface EasyPaperConfigSectionProps {
  t: TFunction;
  palette: VscodeThemePalette;
  form: FormInstance<EasyPaperConfigValues>;
  defaultLlmApiKey: string;
  defaultLlmApiBase: string;
  defaultLlmModel: string;
  modelsBySlot: Record<string, ClaudeModelOption[]>;
  modelsLoadingBySlot: Record<string, boolean>;
  modelsErrorBySlot: Record<string, string | null>;
  onFetchModels: (slot: string, base: string, key: string, apiKind?: 'openai' | 'anthropic') => void;
  onSave: () => void;
  showInlineSave?: boolean;
  showIntro?: boolean;
}

export function EasyPaperConfigSection({
  t, defaultLlmApiKey, defaultLlmApiBase, defaultLlmModel, onSave, form,
  modelsBySlot, modelsLoadingBySlot, modelsErrorBySlot, onFetchModels,
  showInlineSave = true, showIntro = true,
}: EasyPaperConfigSectionProps) {
  const values = Form.useWatch([], form) as Partial<EasyPaperConfigValues> | undefined;
  const llmBase = values?.llmBaseUrl ?? '';
  const llmKey = values?.llmApiKey ?? '';
  const vlmBase = values?.vlmBaseUrl ?? '';
  const vlmKey = values?.vlmApiKey ?? '';
  const vlmEnabled = Boolean(values?.vlmEnabled);
  const vlmApiKind = values?.vlmProvider === 'claude' ? 'anthropic' : 'openai';
  const requestedConnections = React.useRef<Record<string, string>>({});
  const requestModels = React.useCallback((slot: string, base: string, key: string, apiKind: 'openai' | 'anthropic') => {
    requestedConnections.current[slot] = `${base}::${key}::${apiKind}`;
    onFetchModels(slot, base, key, apiKind);
  }, [onFetchModels]);
  const required = [{ required: true, whitespace: true, message: t('easyPaperConfig.required') }];

  React.useEffect(() => {
    if (!llmBase.trim() || !llmKey.trim()) {
      requestModels(ENV_LLM_SLOT.easyPaperLlm, llmBase, llmKey, 'openai');
      return;
    }
    const timer = window.setTimeout(() => requestModels(ENV_LLM_SLOT.easyPaperLlm, llmBase, llmKey, 'openai'), 800);
    return () => window.clearTimeout(timer);
  }, [llmBase, llmKey, requestModels]);

  React.useEffect(() => {
    if (!vlmEnabled || !vlmBase.trim() || !vlmKey.trim()) {
      requestModels(ENV_LLM_SLOT.easyPaperVlm, '', '', vlmApiKind);
      return;
    }
    const timer = window.setTimeout(() => requestModels(ENV_LLM_SLOT.easyPaperVlm, vlmBase, vlmKey, vlmApiKind), 800);
    return () => window.clearTimeout(timer);
  }, [vlmBase, vlmKey, vlmEnabled, vlmApiKind, requestModels]);

  const handleCopyFromAgentSociety = () => {
    form.setFieldsValue({ llmModelName: defaultLlmModel, llmApiKey: defaultLlmApiKey, llmBaseUrl: defaultLlmApiBase });
  };

  const handlePresetChange = (id: string) => {
    const preset = SIM_LLM_PRESETS.find((entry) => entry.id === id);
    if (!preset) { return; }
    if (id === 'custom') {
      form.setFieldsValue({ llmBaseUrl: '', llmApiKey: '', llmModelName: '' });
      return;
    }
    if (matchSimLlmPreset(llmBase) !== id) {
      form.setFieldsValue({ llmBaseUrl: preset.baseUrl, llmApiKey: '', llmModelName: '' });
    }
  };

  const modelField = (slot: string, base: string, key: string, apiKind: 'openai' | 'anthropic') => (
    <EnvLlmModelField
      t={t}
      models={requestedConnections.current[slot] === `${base}::${key}::${apiKind}` && base.trim() && key.trim() ? (modelsBySlot[slot] ?? []) : []}
      loading={modelsLoadingBySlot[slot] ?? false}
      error={modelsErrorBySlot[slot] ?? null}
      canFetch={Boolean(base.trim() && key.trim())}
      onFetch={() => requestModels(slot, base, key, apiKind)}
      placeholder={t('easyPaperConfig.modelNamePlaceholder')}
    />
  );

  return (
    <div style={tabBodyStyle}>
      {showIntro ? <Alert type="info" showIcon style={{ marginBottom: 16 }}
        message={t('easyPaperConfig.infoTitle')} description={t('easyPaperConfig.infoDescription')} /> : null}
      <Form form={form} layout="vertical" component={false}>
        <Text strong style={{ display: 'block', marginBottom: 8 }}>{t('easyPaperConfig.llmSection')}</Text>
        <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>{t('easyPaperConfig.llmSectionHint')}</Text>
        <Button size="small" icon={<CopyOutlined />} onClick={handleCopyFromAgentSociety}
          disabled={!defaultLlmApiKey} style={{ marginBottom: 12 }}>
          {t('easyPaperConfig.copyFromAgentSociety')}
        </Button>
        <Form.Item label={t('configPage.llm.presetLabel')}>
          <Select value={matchSimLlmPreset(llmBase)} onChange={handlePresetChange}
            options={SIM_LLM_PRESETS.map((preset) => ({ value: preset.id, label: t(preset.labelKey) }))} />
        </Form.Item>
        <Form.Item name="llmBaseUrl" label="Base URL" rules={required}>
          <Input placeholder={t('easyPaperConfig.baseUrlPlaceholder')} autoComplete="off" />
        </Form.Item>
        <Form.Item name="llmApiKey" label="API Key" rules={required}>
          <Input.Password placeholder={t('easyPaperConfig.apiKeyPlaceholder')} autoComplete="off" />
        </Form.Item>
        <Form.Item name="llmModelName" label={t('easyPaperConfig.modelName')} rules={required}>
          {modelField(ENV_LLM_SLOT.easyPaperLlm, llmBase, llmKey, 'openai')}
        </Form.Item>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '16px 0' }}>
          <Form.Item name="vlmEnabled" valuePropName="checked" noStyle><Switch size="small" /></Form.Item>
          <Text strong>{t('easyPaperConfig.vlmSection')}</Text>
          <Text type="secondary">{t('easyPaperConfig.vlmOptional')}</Text>
        </div>
        {vlmEnabled ? <>
          <Alert type="info" showIcon message={t('easyPaperConfig.visionHint')} style={{ marginBottom: 12 }} />
          <Button size="small" icon={<CopyOutlined />} disabled={!llmBase || !llmKey}
            onClick={() => form.setFieldsValue({ vlmProvider: 'openai', vlmBaseUrl: llmBase, vlmApiKey: llmKey })}
            style={{ marginBottom: 12 }}>{t('easyPaperConfig.copyLlmConnection')}</Button>
          <Form.Item name="vlmProvider" label={t('easyPaperConfig.vlmProvider')} rules={required}>
            <Select options={[{ value: 'openai', label: 'OpenAI-compatible' }, { value: 'claude', label: 'Anthropic' }, { value: 'qwen', label: 'Qwen (DashScope)' }]} />
          </Form.Item>
          <Form.Item name="vlmBaseUrl" label="Base URL" rules={required}>
            <Input placeholder={t('easyPaperConfig.baseUrlPlaceholder')} autoComplete="off" />
          </Form.Item>
          <Form.Item name="vlmApiKey" label="API Key" rules={required}>
            <Input.Password placeholder={t('easyPaperConfig.apiKeyPlaceholder')} autoComplete="off" />
          </Form.Item>
          <Form.Item name="vlmModel" label={t('easyPaperConfig.vlmModel')} rules={required}>
            {modelField(ENV_LLM_SLOT.easyPaperVlm, vlmBase, vlmKey, vlmApiKind)}
          </Form.Item>
        </> : null}
        {showInlineSave ? <div style={{ display: 'flex', gap: 8 }}>
          <Button type="primary" icon={<SaveOutlined />} onClick={onSave}>{t('easyPaperConfig.save')}</Button>
          <Text type="secondary">{t('easyPaperConfig.saveHint')}</Text>
        </div> : null}
      </Form>
    </div>
  );
}
