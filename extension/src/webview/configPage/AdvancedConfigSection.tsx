import * as React from 'react';
import {
  Form,
  Input,
  InputNumber,
  Tabs,
  Typography,
} from 'antd';
import { FileTextOutlined } from '@ant-design/icons';
import type { FormInstance } from 'antd';
import type { TFunction } from 'i18next';
import type { VscodeThemePalette } from '../theme';
import type { ClaudeModelOption } from './claudeCodeTypes';
import type { ConfigValues, ValidationState, EasyPaperConfigValues } from './types';
import { ValidationAction } from './ValidationAction';
import { PythonEnvironmentPicker, type PythonEnvironmentOption } from './PythonEnvironmentPicker';
import { EnvLlmModelField } from './EnvLlmModelField';
import { ThinkingSelect } from './ThinkingSelect';
import { EasyPaperConfigSection } from './EasyPaperConfigSection';
import { tabBodyStyle } from './configPageStyles';
import {
  type AdvancedValidationKey,
  getAdvancedItemVisualStatus,
  statusColor,
} from './advancedValidation';
import { ENV_LLM_SLOT } from './envLlmSlots';

const { Text } = Typography;

export type AdvancedTopTab = 'models' | 'python' | 'easypaper';

type SpecializedLlmKind = 'coder' | 'embedding';

export interface AdvancedConfigSectionProps {
  t: TFunction;
  palette: VscodeThemePalette;
  hasDefaultLlmKey: boolean;
  defaultLlmApiBase: string;
  defaultLlmModel: string;
  activeTopTab: AdvancedTopTab;
  onActiveTopTabChange: (tab: AdvancedTopTab) => void;
  validationState: Record<string, ValidationState>;
  validateDisabledByKind: Record<SpecializedLlmKind, string | null>;
  pythonValidateDisabledReason: string | null;
  onValidate: (llmType: string) => void;
  pythonSectionRef: React.RefObject<HTMLDivElement | null>;
  form: FormInstance<ConfigValues>;
  modelsBySlot: Record<string, ClaudeModelOption[]>;
  modelsLoadingBySlot: Record<string, boolean>;
  modelsErrorBySlot: Record<string, string | null>;
  onFetchSlotModels: (slotId: string, baseUrl: string, apiKey: string) => void;
  effectiveValues: ConfigValues;
  pythonEnvironmentOptions: PythonEnvironmentOption[];
  pythonEnvironmentScanning: boolean;
  onScanPythonEnvironments: () => void;
  easyPaperForm: FormInstance<EasyPaperConfigValues>;
  onSaveEasyPaper: () => void;
}

export const AdvancedConfigSection: React.FC<AdvancedConfigSectionProps> = ({
  t,
  palette,
  hasDefaultLlmKey,
  defaultLlmApiBase,
  defaultLlmModel,
  activeTopTab,
  onActiveTopTabChange,
  validationState,
  validateDisabledByKind,
  pythonValidateDisabledReason,
  onValidate,
  pythonSectionRef,
  form,
  modelsBySlot,
  modelsLoadingBySlot,
  modelsErrorBySlot,
  onFetchSlotModels,
  effectiveValues,
  pythonEnvironmentOptions,
  pythonEnvironmentScanning,
  onScanPythonEnvironments,
  easyPaperForm,
  onSaveEasyPaper,
}) => {
  const linkedKeyPlaceholder = t('configPage.linkedPlaceholders.apiKey', {
    status: hasDefaultLlmKey
      ? t('configPage.linkedPlaceholders.configured')
      : t('configPage.linkedPlaceholders.notConfigured'),
  });
  const linkedBasePlaceholder = t('configPage.linkedPlaceholders.apiBase', {
    base: defaultLlmApiBase,
  });
  const blockedByKind: Record<AdvancedValidationKey, string | null> = {
    coder: validateDisabledByKind.coder,
    embedding: validateDisabledByKind.embedding,
    python: pythonValidateDisabledReason,
    literature: null,
  };

  const tabLabelWithStatus = (label: string, kind: AdvancedValidationKey) => {
    const blocked = blockedByKind[kind];
    const visual = getAdvancedItemVisualStatus(validationState[kind], blocked);
    const dotColor = statusColor(visual, palette);
    return (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: '50%',
            background: dotColor,
            flexShrink: 0,
          }}
        />
        {label}
      </span>
    );
  };

  const renderValidationAction = (kind: AdvancedValidationKey) => (
    <ValidationAction
      t={t}
      palette={palette}
      state={validationState[kind] ?? { validating: false, valid: null, error: null }}
      disabledReason={blockedByKind[kind]}
      onValidate={() => onValidate(kind)}
      label={t('configPage.validate')}
      size="small"
      primary={false}
    />
  );

  const slotFetchProps = (slotId: string, baseUrl: string | undefined, apiKey: string | undefined) => ({
    models: modelsBySlot[slotId] ?? [],
    loading: modelsLoadingBySlot[slotId] ?? false,
    error: modelsErrorBySlot[slotId] ?? null,
    canFetch: Boolean((baseUrl ?? '').trim() && (apiKey ?? '').trim()),
    onFetch: () => onFetchSlotModels(slotId, baseUrl ?? '', apiKey ?? ''),
  });

  const coderBase = (effectiveValues.coderLlmApiBase || effectiveValues.llmApiBase || '').trim();
  const coderKey = (effectiveValues.coderLlmApiKey || effectiveValues.llmApiKey || '').trim();
  const embeddingBase = (effectiveValues.embeddingApiBase || effectiveValues.llmApiBase || '').trim();
  const embeddingKey = (effectiveValues.embeddingApiKey || effectiveValues.llmApiKey || '').trim();

  const modelTabItems = [
    {
      key: 'coder',
      label: tabLabelWithStatus(t('configPage.coder.shortTitle'), 'coder'),
      children: (
        <div style={tabBodyStyle}>
          <Text type="secondary" style={{ display: 'block', marginBottom: 12, fontSize: 12 }}>
            {t('configPage.coder.hint')}
          </Text>
          <Form.Item name="coderLlmApiBase" label={t('configPage.coder.apiBase')} style={{ marginBottom: 12 }}>
            <Input placeholder={linkedBasePlaceholder} />
          </Form.Item>
          <Form.Item name="coderLlmApiKey" label={t('configPage.coder.apiKey')} style={{ marginBottom: 12 }}>
            <Input.Password placeholder={linkedKeyPlaceholder} autoComplete="off" />
          </Form.Item>
          <Form.Item
            name="coderLlmModel"
            label={t('configPage.coder.model')}
            style={{ marginBottom: 12 }}
          >
            <EnvLlmModelField
              t={t}
              placeholder={t('configPage.coder.modelPlaceholder', { model: defaultLlmModel })}
              {...slotFetchProps(ENV_LLM_SLOT.coder, coderBase, coderKey)}
            />
          </Form.Item>
          <Form.Item
            name="coderLlmThinking"
            label={t('configPage.coder.thinking')}
            tooltip={t('configPage.coder.thinkingHint')}
            style={{ marginBottom: 12 }}
          >
            <ThinkingSelect t={t} scope="coder" />
          </Form.Item>
          {renderValidationAction('coder')}
        </div>
      ),
    },
    {
      key: 'embedding',
      label: tabLabelWithStatus(t('configPage.advanced.embedding.shortTitle'), 'embedding'),
      children: (
        <div style={tabBodyStyle}>
          <Text type="secondary" style={{ display: 'block', marginBottom: 12, fontSize: 12 }}>
            {t('configPage.advanced.embedding.hint')}
          </Text>
          <Form.Item name="embeddingApiBase" label={t('configPage.advanced.embedding.apiBase')}>
            <Input placeholder={linkedBasePlaceholder} />
          </Form.Item>
          <Form.Item name="embeddingApiKey" label={t('configPage.advanced.embedding.apiKey')}>
            <Input.Password placeholder={linkedKeyPlaceholder} autoComplete="off" />
          </Form.Item>
          <Form.Item name="embeddingModel" label={t('configPage.advanced.embedding.model')}>
            <EnvLlmModelField
              t={t}
              placeholder={t('configPage.advanced.embedding.modelPlaceholder')}
              {...slotFetchProps(ENV_LLM_SLOT.embedding, embeddingBase, embeddingKey)}
            />
          </Form.Item>
          <Form.Item name="embeddingDims" label={t('configPage.advanced.embedding.dims')}>
            <InputNumber
              min={64}
              max={4096}
              style={{ width: '100%' }}
              placeholder={t('configPage.advanced.embedding.dimsPlaceholder')}
            />
          </Form.Item>
          {renderValidationAction('embedding')}
        </div>
      ),
    },
  ];

  const topTabItems = [
    {
      key: 'models',
      label: t('configPage.sections.specializedModels'),
      children: (
        <>
          <Text type="secondary" style={{ display: 'block', fontSize: 12, marginBottom: 8 }}>
            {t('configPage.sections.inheritHintShort')}
          </Text>
          <Tabs size="small" destroyInactiveTabPane={false} items={modelTabItems} />
        </>
      ),
    },
    {
      key: 'python',
      label: tabLabelWithStatus(t('configPage.python.title'), 'python'),
      children: (
        <div ref={pythonSectionRef} style={tabBodyStyle}>
          <Text type="secondary" style={{ display: 'block', fontSize: 12, marginBottom: 12 }}>
            {t('configPage.python.hint')}
          </Text>
          <PythonEnvironmentPicker
            t={t}
            form={form}
            options={pythonEnvironmentOptions}
            scanning={pythonEnvironmentScanning}
            onScan={onScanPythonEnvironments}
          />
          {renderValidationAction('python')}
        </div>
      ),
    },
    {
      key: 'easypaper',
      label: (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <FileTextOutlined />
          EasyPaper
        </span>
      ),
      children: (
        <EasyPaperConfigSection
          t={t}
          palette={palette}
          form={easyPaperForm}
          defaultLlmApiKey={hasDefaultLlmKey ? (effectiveValues.llmApiKey || '') : ''}
          defaultLlmApiBase={defaultLlmApiBase}
          defaultLlmModel={defaultLlmModel}
          onSave={onSaveEasyPaper}
        />
      ),
    },
  ];

  return (
    <Tabs
      activeKey={activeTopTab}
      onChange={(key) => onActiveTopTabChange(key as AdvancedTopTab)}
      items={topTabItems}
      size="middle"
      destroyInactiveTabPane={false}
    />
  );
};
