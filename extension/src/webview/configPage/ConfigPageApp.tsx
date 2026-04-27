import * as React from 'react';
import {
  ConfigProvider,
  Layout,
  Form,
  Input,
  InputNumber,
  Button,
  Card,
  Typography,
  Alert,
  Space,
  notification,
  Collapse,
  Tooltip,
  Tag,
} from 'antd';
import { SaveOutlined, KeyOutlined, CheckCircleOutlined, RocketOutlined, QuestionCircleOutlined, ReloadOutlined, ApiOutlined, SettingOutlined, CloudServerOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import type { VSCodeAPI, ConfigValues, WorkspaceInfo } from './types';
import { useVscodeTheme } from '../theme';
import 'antd/dist/reset.css';

const { Content } = Layout;
const { Title, Text } = Typography;

const DEFAULT_VALUES: ConfigValues = {
  llmApiKey: '',
  backendHost: '127.0.0.1',
  backendPort: 8001,
  pythonPath: '',
  llmApiBase: 'https://api.openai.com/v1',
  llmModel: 'gpt-5.4',
  backendLogLevel: 'info',
  coderLlmApiKey: '',
  coderLlmApiBase: 'https://api.openai.com/v1',
  coderLlmModel: '',
  nanoLlmApiKey: '',
  nanoLlmApiBase: 'https://api.openai.com/v1',
  nanoLlmModel: '',
  analysisLlmApiKey: '',
  analysisLlmApiBase: 'https://api.openai.com/v1',
  analysisLlmModel: '',
  embeddingApiKey: '',
  embeddingApiBase: 'https://api.openai.com/v1',
  embeddingModel: 'text-embedding-3-large',
  embeddingDims: 1024,
  webSearchApiUrl: '',
  webSearchApiToken: '',
  miroflowDefaultLlm: 'qwen-3',
  miroflowDefaultAgent: 'mirothinker_v1.5_keep5_max200',
  easypaperApiUrl: '',
  easypaperLlmApiKey: '',
  easypaperLlmModel: '',
  easypaperVlmModel: '',
  easypaperVlmApiKey: '',
  literatureSearchApiUrl: 'http://localhost:8008/api/search',
  literatureSearchApiKey: '',
};

interface ConfigPageAppProps {
  vscode: VSCodeAPI;
}

interface ValidationState {
  validating: boolean;
  valid: boolean | null;
  error: string | null;
}

export const ConfigPageApp: React.FC<ConfigPageAppProps> = ({ vscode }) => {
  const { t } = useTranslation();
  const { isDark, palette, themeConfig } = useVscodeTheme();
  const [form] = Form.useForm<ConfigValues>();
  const watchedValues = Form.useWatch([], form) as Partial<ConfigValues> | undefined;
  const currentValues = watchedValues || {};
  const hasText = (value?: string) => Boolean(value && value.trim());
  const defaultLlmModel = (currentValues.llmModel || DEFAULT_VALUES.llmModel || '').trim();
  const defaultLlmApiBase = (currentValues.llmApiBase || DEFAULT_VALUES.llmApiBase || '').trim();
  const hasDefaultLlmKey = hasText(currentValues.llmApiKey);

  const getEffectiveApiKey = (values: Partial<ConfigValues>, llmType: string): string => {
    switch (llmType) {
      case 'coder':
        return (values.coderLlmApiKey || values.llmApiKey || '').trim();
      case 'nano':
        return (values.nanoLlmApiKey || values.llmApiKey || '').trim();
      case 'analysis':
        return (values.analysisLlmApiKey || values.llmApiKey || '').trim();
      case 'embedding':
        return (values.embeddingApiKey || values.llmApiKey || '').trim();
      case 'easypaperVlm':
        return (values.easypaperVlmApiKey || values.easypaperLlmApiKey || values.llmApiKey || '').trim();
      default:
        return (values.llmApiKey || '').trim();
    }
  };

  const getEffectiveApiBase = (values: Partial<ConfigValues>, llmType: string): string => {
    switch (llmType) {
      case 'coder':
        return (values.coderLlmApiBase || values.llmApiBase || '').trim();
      case 'nano':
        return (values.nanoLlmApiBase || values.llmApiBase || '').trim();
      case 'analysis':
        return (values.analysisLlmApiBase || values.llmApiBase || '').trim();
      case 'embedding':
        return (values.embeddingApiBase || values.llmApiBase || '').trim();
      case 'easypaperVlm':
        return (values.llmApiBase || '').trim();
      default:
        return (values.llmApiBase || '').trim();
    }
  };

  const getValidationDisabledReason = (llmType: string, values: Partial<ConfigValues>): string | null => {
    if (llmType === 'default') {
      if (!hasText(values.llmApiKey)) {
        return t('configPage.notifications.apiKeyMissing');
      }
      if (!hasText(values.llmApiBase)) {
        return t('configPage.notifications.apiBaseMissing');
      }
      return null;
    }

    if (llmType === 'literature') {
      return hasText(values.literatureSearchApiUrl) ? null : t('configPage.validation.literatureUrlRequired');
    }

    const apiKey = getEffectiveApiKey(values, llmType);
    if (!hasText(apiKey)) {
      return t('configPage.validation.needsApiKey');
    }

    const apiBase = getEffectiveApiBase(values, llmType);
    if (!hasText(apiBase)) {
      return t('configPage.validation.needsApiBase');
    }

    return null;
  };

  const defaultValidateDisabledReason = getValidationDisabledReason('default', currentValues);
  const coderValidateDisabledReason = getValidationDisabledReason('coder', currentValues);
  const nanoValidateDisabledReason = getValidationDisabledReason('nano', currentValues);
  const analysisValidateDisabledReason = getValidationDisabledReason('analysis', currentValues);
  const embeddingValidateDisabledReason = getValidationDisabledReason('embedding', currentValues);
  const pythonValidateDisabledReason = null;
  const easypaperVlmValidateDisabledReason = getValidationDisabledReason('easypaperVlm', currentValues);
  const literatureValidateDisabledReason = getValidationDisabledReason('literature', currentValues);
  const [loading, setLoading] = React.useState(false);
  const [startingBackend, setStartingBackend] = React.useState(false);
  const [workspaceInfo, setWorkspaceInfo] = React.useState<WorkspaceInfo>({ hasWorkspace: false });

  // Validation status for each LLM type
  const [validationState, setValidationState] = React.useState<Record<string, ValidationState>>({
    default: { validating: false, valid: null, error: null },
    coder: { validating: false, valid: null, error: null },
    nano: { validating: false, valid: null, error: null },
    analysis: { validating: false, valid: null, error: null },
    embedding: { validating: false, valid: null, error: null },
    easypaperVlm: { validating: false, valid: null, error: null },
    python: { validating: false, valid: null, error: null },
    literature: { validating: false, valid: null, error: null },
  });

  // 计算配置统计
  const getConfigStats = () => {
    const values = currentValues;
    const llmServices = [
      { key: 'llm', name: 'Default LLM', hasKey: hasText(values.llmApiKey), hasBase: hasText(values.llmApiBase), hasModel: hasText(values.llmModel) },
      { key: 'coder', name: 'Coder', hasKey: hasText(values.coderLlmApiKey), hasBase: hasText(values.coderLlmApiBase), hasModel: hasText(values.coderLlmModel) },
      { key: 'nano', name: 'Nano', hasKey: hasText(values.nanoLlmApiKey), hasBase: hasText(values.nanoLlmApiBase), hasModel: hasText(values.nanoLlmModel) },
      { key: 'analysis', name: 'Analysis', hasKey: hasText(values.analysisLlmApiKey), hasBase: hasText(values.analysisLlmApiBase), hasModel: hasText(values.analysisLlmModel) },
      { key: 'embedding', name: 'Embedding', hasKey: hasText(values.embeddingApiKey), hasBase: hasText(values.embeddingApiBase), hasModel: hasText(values.embeddingModel) },
    ];

    const configuredServices = llmServices.filter(s => s.hasKey || (s.key === 'llm' && hasText(values.llmApiKey))).length;
    const validatedServices = Object.entries(validationState).filter(([key, state]) => state.valid === true).length;
    const hasPython = hasText(values.pythonPath);

    return { configuredServices, validatedServices, hasPython, totalServices: llmServices.length };
  };

  const stats = getConfigStats();

  // Reset to default values
  const handleResetDefaults = () => {
    form.setFieldsValue(DEFAULT_VALUES);
    notification.info({
      message: t('configPage.resetDefaults'),
      placement: 'top',
    });
  };

  // Validation handler - reads current form values
  const handleValidate = async (llmType: string) => {
    const values = form.getFieldsValue();

    // Special handling for Python validation
    if (llmType === 'python') {
      setValidationState(prev => ({ ...prev, python: { validating: true, valid: null, error: null } }));
      vscode.postMessage({
        command: 'validatePython',
        config: values,
      });
      return;
    }

    // For coder/nano/analysis/embedding, check if default LLM config is filled in the form
    if (['coder', 'nano', 'analysis', 'embedding', 'easypaperVlm'].includes(llmType)) {
      const effectiveApiKey = getEffectiveApiKey(values, llmType);
      if (!effectiveApiKey) {
        notification.warning({
          message: t('configPage.validationFailed'),
          description: t('configPage.validation.needsApiKey'),
          placement: 'top',
        });
        return;
      }
      const effectiveApiBase = getEffectiveApiBase(values, llmType);
      if (!effectiveApiBase) {
        notification.warning({
          message: t('configPage.validationFailed'),
          description: t('configPage.validation.needsApiBase'),
          placement: 'top',
        });
        return;
      }

      setValidationState(prev => ({ ...prev, [llmType]: { validating: true, valid: null, error: null } }));
      vscode.postMessage({
        command: 'validateConfig',
        config: values,
        llmType,
      });
      return;
    }

    // For default LLM, check required fields
    if (llmType === 'default') {
      const missingField = !values.llmApiKey ? t('configPage.notifications.apiKeyMissing') : !values.llmApiBase ? t('configPage.notifications.apiBaseMissing') : '';
      if (missingField) {
        notification.warning({
          message: t('configPage.validationFailed'),
          description: missingField,
          placement: 'top',
        });
        return;
      }
      setValidationState(prev => ({ ...prev, [llmType]: { validating: true, valid: null, error: null } }));
      vscode.postMessage({
        command: 'validateConfig',
        config: values,
        llmType,
      });
      return;
    }

    // For literature search, validate API URL and Key
    if (llmType === 'literature') {
      if (!values.literatureSearchApiUrl) {
        notification.warning({
          message: t('configPage.validationFailed'),
          description: '请输入文献检索 API URL',
          placement: 'top',
        });
        return;
      }
      setValidationState(prev => ({ ...prev, [llmType]: { validating: true, valid: null, error: null } }));
      vscode.postMessage({
        command: 'validateLiteratureSearch',
        config: values,
      });
      return;
    }
  };

  React.useEffect(() => {
    vscode.postMessage({ command: 'requestConfig' });
  }, [vscode]);

  React.useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      const message = event.data as { command: string;[key: string]: any };

      if (message.command === 'initialConfig') {
        const config = message.config || {};
        form.setFieldsValue({
          ...DEFAULT_VALUES,
          ...config,
        });
      } else if (message.command === 'workspaceInfo') {
        setWorkspaceInfo(message.workspaceInfo || { hasWorkspace: false });
      } else if (message.command === 'saveResult') {
        const msg = message as { success?: boolean; error?: string };
        setLoading(false);
        if (msg.success) {
          notification.success({
            message: t('configPage.notifications.saveSuccess'),
            description: t('configPage.notifications.saveSuccessDesc'),
            placement: 'top',
          });
        } else if (msg.error) {
          notification.error({
            message: t('configPage.notifications.saveFailed'),
            description: msg.error,
            placement: 'top',
          });
        }
      } else if (message.command === 'startBackendResult') {
        const msg = message as { success?: boolean; error?: string };
        setStartingBackend(false);
        if (msg.success) {
          notification.success({
            message: t('configPage.notifications.backendStarted', { defaultValue: 'Backend started successfully' }),
            placement: 'top',
          });
          setTimeout(() => {
            vscode.postMessage({ command: 'closeConfigPage' });
          }, 1500);
        } else if (msg.error) {
          notification.error({
            message: t('configPage.notifications.backendStartFailed', { defaultValue: 'Failed to start backend' }),
            description: msg.error,
            placement: 'top',
            duration: 6,
          });
        }
      } else if (message.command === 'validationResult') {
        const msg = message as unknown as { llmType: string; success?: boolean; error?: string };
        setValidationState(prev => ({
          ...prev,
          [msg.llmType]: { validating: false, valid: msg.success ?? false, error: msg.error || null },
        }));
      } else if (message.command === 'literatureValidationResult') {
        const msg = message as { success?: boolean; error?: string; sources?: Record<string, unknown> };
        setValidationState(prev => ({
          ...prev,
          literature: { validating: false, valid: msg.success ?? false, error: msg.error || null },
        }));
        if (msg.success && msg.sources) {
          notification.success({
            message: '文献检索配置验证成功',
            description: `服务已连接，数据源: ${Object.keys(msg.sources).join(', ')}`,
            placement: 'top',
          });
        }
      }
    };

    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [form, vscode]);

  const handleSave = async () => {
    if (!workspaceInfo.hasWorkspace) {
      notification.warning({
        message: t('configPage.noWorkspace'),
        description: t('configPage.noWorkspaceHint'),
      });
      return;
    }

    const values = form.getFieldsValue();

    // Require LLM API key to save
    if (!values.llmApiKey) {
      notification.warning({
        message: t('configPage.notifications.llmKeyRequired'),
        description: t('configPage.notifications.llmKeyRequiredDesc'),
      });
      return;
    }

    setLoading(true);
    vscode.postMessage({
      command: 'saveConfig',
      config: values,
    });
  };

  const handleSaveAndStart = async () => {
    if (!workspaceInfo.hasWorkspace) {
      notification.warning({
        message: t('configPage.noWorkspace'),
        description: t('configPage.noWorkspaceHint'),
      });
      return;
    }

    const values = form.getFieldsValue();

    // Require LLM API key
    if (!values.llmApiKey) {
      notification.warning({
        message: t('configPage.notifications.llmKeyRequired'),
        description: t('configPage.notifications.llmKeyRequiredDesc'),
      });
      return;
    }

    setLoading(true);
    setStartingBackend(true);

    // First save, then start backend
    vscode.postMessage({
      command: 'saveConfig',
      config: values,
    });

    // Wait a bit then start backend
    setTimeout(() => {
      vscode.postMessage({
        command: 'startBackend',
        config: values,
      });
    }, 500);
  };

  // 玻璃态样式常量
  const glassStyle = {
    background: isDark
      ? 'rgba(37, 37, 38, 0.75)'
      : 'rgba(255, 255, 255, 0.72)',
    backdropFilter: 'blur(20px)',
    WebkitBackdropFilter: 'blur(20px)',
  };

  // 统计卡片
  const statPill = (label: string, value: string | number, icon: React.ReactNode, accent?: string) => (
    <div
      style={{
        flex: '1 1 100px',
        minWidth: 90,
        padding: '12px 16px',
        borderRadius: 10,
        border: `1px solid ${palette.panelBorder}`,
        background: isDark
          ? 'rgba(37, 37, 38, 0.6)'
          : 'rgba(255, 255, 255, 0.55)',
        backdropFilter: 'blur(16px)',
        WebkitBackdropFilter: 'blur(16px)',
        boxShadow: '0 2px 8px rgba(0,0,0,0.06)',
        transition: 'all 0.2s ease',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
        <span style={{ color: accent ?? palette.linkForeground }}>{icon}</span>
        <span style={{ fontSize: 11, color: palette.descriptionForeground, fontWeight: 500 }}>{label}</span>
      </div>
      <div style={{ fontSize: 20, fontWeight: 700, color: accent ?? palette.editorForeground, lineHeight: 1 }}>
        {value}
      </div>
    </div>
  );

  return (
    <ConfigProvider theme={themeConfig}>
      <Layout style={{ minHeight: '100vh', background: palette.editorBackground }}>
        <Content
          style={{
            padding: '20px 24px',
            maxWidth: 920,
            margin: '0 auto',
            width: '100%',
            color: palette.editorForeground,
          }}
        >
          {/* 头部区域 - 玻璃态 */}
          <div
            style={{
              marginBottom: 20,
              padding: '20px 24px',
              borderRadius: 16,
              border: `1px solid ${palette.panelBorder}`,
              background: isDark
                ? 'rgba(37, 37, 38, 0.7)'
                : 'rgba(255, 255, 255, 0.65)',
              backdropFilter: 'blur(24px)',
              WebkitBackdropFilter: 'blur(24px)',
              boxShadow: isDark
                ? '0 4px 16px rgba(0,0,0,0.2)'
                : '0 4px 16px rgba(0,0,0,0.08)',
            }}
          >
            <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 16, marginBottom: 16 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <span
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    width: 40,
                    height: 40,
                    borderRadius: 12,
                    background: `linear-gradient(135deg, ${palette.linkForeground}20 0%, ${palette.linkForeground}10 100%)`,
                    color: palette.linkForeground,
                  }}
                >
                  <SettingOutlined style={{ fontSize: 18 }} />
                </span>
                <div>
                  <Title level={4} style={{ margin: 0 }}>{t('configPage.title')}</Title>
                  <Text type="secondary" style={{ fontSize: 12 }}>{t('configPage.subtitle')}</Text>
                </div>
              </div>
            </div>

            {/* 统计卡片 */}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
              {statPill('已配置服务', `${stats.configuredServices}/${stats.totalServices}`, <ApiOutlined />, palette.linkForeground)}
              {statPill('验证通过', stats.validatedServices, <CheckCircleOutlined />, palette.successForeground)}
              {statPill('Python 环境', stats.hasPython ? '已配置' : '默认', <CloudServerOutlined />)}
            </div>
          </div>

          {!workspaceInfo.hasWorkspace && (
            <Alert
              message={t('configPage.noWorkspace')}
              description={t('configPage.noWorkspaceHint')}
              type="warning"
              showIcon
              style={{ marginBottom: 16, borderRadius: 10 }}
            />
          )}

          <Form form={form} style={{ marginBottom: 20 }}>
            {/* ========== 必填配置 - 玻璃态卡片 ========== */}
            <Card
              title={
                <Space>
                  <KeyOutlined style={{ color: palette.errorForeground }} />
                  <span>LLM 配置</span>
                  <Tag color="red" style={{ marginLeft: 4 }}>必填</Tag>
                </Space>
              }
              style={{
                marginBottom: 16,
                borderRadius: 12,
                border: `1px solid ${palette.panelBorder}`,
                background: isDark
                  ? 'rgba(37, 37, 38, 0.6)'
                  : 'rgba(255, 255, 255, 0.5)',
                backdropFilter: 'blur(16px)',
                WebkitBackdropFilter: 'blur(16px)',
                boxShadow: '0 2px 10px rgba(0,0,0,0.06)',
              }}
              styles={{ body: { padding: '16px 20px' } }}
            >
              <Form.Item
                name="llmApiKey"
                label={t('configPage.llm.apiKeyRequired')}
                rules={[{ required: true, message: t('configPage.notifications.apiKeyMissing') }]}
                tooltip={t('configPage.llm.apiKeyRequiredHint')}
              >
                <Input.Password placeholder={t('configPage.llm.apiKeyPlaceholder')} autoComplete="off" />
              </Form.Item>
              <Form.Item name="llmApiBase" label={t('configPage.llm.apiBase')}>
                <Input placeholder={t('configPage.llm.apiBasePlaceholder')} />
              </Form.Item>
              <Form.Item name="llmModel" label={t('configPage.llm.modelName')}>
                <Input placeholder={t('configPage.llm.modelPlaceholder')} />
              </Form.Item>
              {validationState.default.error && (
                <Alert type="error" message={t('configPage.validationFailed')} description={validationState.default.error} style={{ marginBottom: 12, borderRadius: 8 }} />
              )}
              {validationState.default.valid && (
                <Alert type="success" message={t('configPage.validationSuccess')} style={{ marginBottom: 12, borderRadius: 8 }} />
              )}
              <Tooltip title={defaultValidateDisabledReason || ''}>
                <Button
                  type="primary"
                  icon={<CheckCircleOutlined />}
                  onClick={() => handleValidate('default')}
                  loading={validationState.default?.validating}
                  disabled={Boolean(defaultValidateDisabledReason)}
                >
                  {t('configPage.validate')}
                </Button>
              </Tooltip>
            </Card>

            {/* ========== 可选配置（折叠）========== */}
            <Collapse
              bordered={false}
              style={{
                marginBottom: 16,
                background: 'transparent',
              }}
              items={[
                {
                  key: 'advanced',
                  label: <span style={{ fontWeight: 500 }}>{t('configPage.advancedConfig')}</span>,
                  children: (
                    <>
                      {/* 代码生成 LLM */}
                      <Card
                        size="small"
                        title={
                          <Space>
                            <span>{t('configPage.coder.title')}</span>
                            <Tooltip title={t('configPage.coder.hint')}><QuestionCircleOutlined style={{ color: palette.descriptionForeground }} /></Tooltip>
                          </Space>
                        }
                        style={{
                          marginBottom: 12,
                          borderRadius: 10,
                          border: `1px solid ${palette.panelBorder}`,
                          background: isDark
                            ? 'rgba(37, 37, 38, 0.5)'
                            : 'rgba(255, 255, 255, 0.45)',
                          backdropFilter: 'blur(12px)',
                          WebkitBackdropFilter: 'blur(12px)',
                        }}
                        styles={{ body: { padding: '12px 16px' } }}
                      >
                        <Form.Item name="coderLlmApiKey" label={t('configPage.coder.apiKey')}>
                          <Input.Password
                            placeholder={t('configPage.linkedPlaceholders.apiKey', {
                              status: hasDefaultLlmKey
                                ? t('configPage.linkedPlaceholders.configured')
                                : t('configPage.linkedPlaceholders.notConfigured'),
                            })}
                            autoComplete="off"
                          />
                        </Form.Item>
                        <Form.Item name="coderLlmApiBase" label={t('configPage.coder.apiBase')}>
                          <Input placeholder={t('configPage.linkedPlaceholders.apiBase', { base: defaultLlmApiBase })} />
                        </Form.Item>
                        <Form.Item name="coderLlmModel" label={t('configPage.coder.model')}>
                          <Input placeholder={t('configPage.coder.modelPlaceholder', { model: defaultLlmModel })} />
                        </Form.Item>
                        {validationState.coder.error && <Alert type="error" message={t('configPage.validationFailed')} description={validationState.coder.error} style={{ marginBottom: 8, borderRadius: 6 }} />}
                        {validationState.coder.valid && <Alert type="success" message={t('configPage.validationSuccess')} style={{ marginBottom: 8, borderRadius: 6 }} />}
                        <Tooltip title={coderValidateDisabledReason || ''}>
                          <Button
                            size="small"
                            icon={<CheckCircleOutlined />}
                            onClick={() => handleValidate('coder')}
                            loading={validationState.coder?.validating}
                            disabled={Boolean(coderValidateDisabledReason)}
                          >
                            {t('configPage.validate')}
                          </Button>
                        </Tooltip>
                      </Card>

                      {/* 高频操作 LLM */}
                      <Card
                        size="small"
                        title={
                          <Space>
                            <span>{t('configPage.advanced.nano.title')}</span>
                            <Tooltip title={t('configPage.advanced.nano.hint')}><QuestionCircleOutlined style={{ color: palette.descriptionForeground }} /></Tooltip>
                          </Space>
                        }
                        style={{
                          marginBottom: 12,
                          borderRadius: 10,
                          border: `1px solid ${palette.panelBorder}`,
                          background: isDark
                            ? 'rgba(37, 37, 38, 0.5)'
                            : 'rgba(255, 255, 255, 0.45)',
                          backdropFilter: 'blur(12px)',
                          WebkitBackdropFilter: 'blur(12px)',
                        }}
                        styles={{ body: { padding: '12px 16px' } }}
                      >
                        <Form.Item name="nanoLlmApiKey" label={t('configPage.advanced.nano.apiKey')}>
                          <Input.Password
                            placeholder={t('configPage.linkedPlaceholders.apiKey', {
                              status: hasDefaultLlmKey
                                ? t('configPage.linkedPlaceholders.configured')
                                : t('configPage.linkedPlaceholders.notConfigured'),
                            })}
                            autoComplete="off"
                          />
                        </Form.Item>
                        <Form.Item name="nanoLlmApiBase" label={t('configPage.advanced.nano.apiBase')}>
                          <Input placeholder={t('configPage.linkedPlaceholders.apiBase', { base: defaultLlmApiBase })} />
                        </Form.Item>
                        <Form.Item name="nanoLlmModel" label={t('configPage.advanced.nano.model')}>
                          <Input placeholder={t('configPage.advanced.nano.modelPlaceholder', { model: defaultLlmModel })} />
                        </Form.Item>
                        {validationState.nano.error && <Alert type="error" message={t('configPage.validationFailed')} description={validationState.nano.error} style={{ marginBottom: 8, borderRadius: 6 }} />}
                        {validationState.nano.valid && <Alert type="success" message={t('configPage.validationSuccess')} style={{ marginBottom: 8, borderRadius: 6 }} />}
                        <Tooltip title={nanoValidateDisabledReason || ''}>
                          <Button
                            size="small"
                            icon={<CheckCircleOutlined />}
                            onClick={() => handleValidate('nano')}
                            loading={validationState.nano?.validating}
                            disabled={Boolean(nanoValidateDisabledReason)}
                          >
                            {t('configPage.validate')}
                          </Button>
                        </Tooltip>
                      </Card>

                      {/* 分析 LLM */}
                      <Card
                        size="small"
                        title={
                          <Space>
                            <span>{t('configPage.analysis.title')}</span>
                            <Tooltip title={t('configPage.analysis.hint')}><QuestionCircleOutlined style={{ color: palette.descriptionForeground }} /></Tooltip>
                          </Space>
                        }
                        style={{
                          marginBottom: 12,
                          borderRadius: 10,
                          border: `1px solid ${palette.panelBorder}`,
                          background: isDark
                            ? 'rgba(37, 37, 38, 0.5)'
                            : 'rgba(255, 255, 255, 0.45)',
                          backdropFilter: 'blur(12px)',
                          WebkitBackdropFilter: 'blur(12px)',
                        }}
                        styles={{ body: { padding: '12px 16px' } }}
                      >
                        <Form.Item name="analysisLlmApiKey" label={t('configPage.analysis.apiKey')}>
                          <Input.Password
                            placeholder={t('configPage.linkedPlaceholders.apiKey', {
                              status: hasDefaultLlmKey
                                ? t('configPage.linkedPlaceholders.configured')
                                : t('configPage.linkedPlaceholders.notConfigured'),
                            })}
                            autoComplete="off"
                          />
                        </Form.Item>
                        <Form.Item name="analysisLlmApiBase" label={t('configPage.analysis.apiBase')}>
                          <Input placeholder={t('configPage.linkedPlaceholders.apiBase', { base: defaultLlmApiBase })} />
                        </Form.Item>
                        <Form.Item name="analysisLlmModel" label={t('configPage.analysis.model')}>
                          <Input placeholder={t('configPage.analysis.modelPlaceholder', { model: defaultLlmModel })} />
                        </Form.Item>
                        {validationState.analysis?.error && <Alert type="error" message={t('configPage.validationFailed')} description={validationState.analysis.error} style={{ marginBottom: 8, borderRadius: 6 }} />}
                        {validationState.analysis?.valid && <Alert type="success" message={t('configPage.validationSuccess')} style={{ marginBottom: 8, borderRadius: 6 }} />}
                        <Tooltip title={analysisValidateDisabledReason || ''}>
                          <Button
                            size="small"
                            icon={<CheckCircleOutlined />}
                            onClick={() => handleValidate('analysis')}
                            loading={validationState.analysis?.validating}
                            disabled={Boolean(analysisValidateDisabledReason)}
                          >
                            {t('configPage.validate')}
                          </Button>
                        </Tooltip>
                      </Card>

                      {/* Embedding */}
                      <Card
                        size="small"
                        title={
                          <Space>
                            <span>{t('configPage.advanced.embedding.title')}</span>
                            <Tooltip title={t('configPage.advanced.embedding.hint')}><QuestionCircleOutlined style={{ color: palette.descriptionForeground }} /></Tooltip>
                          </Space>
                        }
                        style={{
                          marginBottom: 12,
                          borderRadius: 10,
                          border: `1px solid ${palette.panelBorder}`,
                          background: isDark
                            ? 'rgba(37, 37, 38, 0.5)'
                            : 'rgba(255, 255, 255, 0.45)',
                          backdropFilter: 'blur(12px)',
                          WebkitBackdropFilter: 'blur(12px)',
                        }}
                        styles={{ body: { padding: '12px 16px' } }}
                      >
                        <Form.Item name="embeddingApiKey" label={t('configPage.advanced.embedding.apiKey')}>
                          <Input.Password
                            placeholder={t('configPage.linkedPlaceholders.apiKey', {
                              status: hasDefaultLlmKey
                                ? t('configPage.linkedPlaceholders.configured')
                                : t('configPage.linkedPlaceholders.notConfigured'),
                            })}
                            autoComplete="off"
                          />
                        </Form.Item>
                        <Form.Item name="embeddingApiBase" label={t('configPage.advanced.embedding.apiBase')}>
                          <Input placeholder={t('configPage.linkedPlaceholders.apiBase', { base: defaultLlmApiBase })} />
                        </Form.Item>
                        <Form.Item name="embeddingModel" label={t('configPage.advanced.embedding.model')}>
                          <Input placeholder={t('configPage.advanced.embedding.modelPlaceholder')} />
                        </Form.Item>
                        <Form.Item name="embeddingDims" label={t('configPage.advanced.embedding.dims')}>
                          <InputNumber min={64} max={4096} style={{ width: '100%' }} placeholder={t('configPage.advanced.embedding.dimsPlaceholder')} />
                        </Form.Item>
                        {validationState.embedding.error && <Alert type="error" message={t('configPage.validationFailed')} description={validationState.embedding.error} style={{ marginBottom: 8, borderRadius: 6 }} />}
                        {validationState.embedding.valid && <Alert type="success" message={t('configPage.validationSuccess')} style={{ marginBottom: 8, borderRadius: 6 }} />}
                        <Tooltip title={embeddingValidateDisabledReason || ''}>
                          <Button
                            size="small"
                            icon={<CheckCircleOutlined />}
                            onClick={() => handleValidate('embedding')}
                            loading={validationState.embedding?.validating}
                            disabled={Boolean(embeddingValidateDisabledReason)}
                          >
                            {t('configPage.validate')}
                          </Button>
                        </Tooltip>
                      </Card>

                      {/* Python 环境 */}
                      <Card
                        size="small"
                        title={
                          <Space>
                            <span>{t('configPage.python.title')}</span>
                            <Tooltip title={t('configPage.python.hint')}><QuestionCircleOutlined style={{ color: palette.descriptionForeground }} /></Tooltip>
                          </Space>
                        }
                        style={{
                          marginBottom: 12,
                          borderRadius: 10,
                          border: `1px solid ${palette.panelBorder}`,
                          background: isDark
                            ? 'rgba(37, 37, 38, 0.5)'
                            : 'rgba(255, 255, 255, 0.45)',
                          backdropFilter: 'blur(12px)',
                          WebkitBackdropFilter: 'blur(12px)',
                        }}
                        styles={{ body: { padding: '12px 16px' } }}
                      >
                        <Form.Item name="pythonPath" label={t('configPage.python.path')}>
                          <Input placeholder={t('configPage.python.pathPlaceholder')} />
                        </Form.Item>
                        {validationState.python.error && <Alert type="error" message={t('configPage.validationFailed')} description={validationState.python.error} style={{ marginBottom: 8, borderRadius: 6 }} />}
                        {validationState.python.valid && <Alert type="success" message={t('configPage.validationSuccess')} style={{ marginBottom: 8, borderRadius: 6 }} />}
                        <Tooltip title={pythonValidateDisabledReason || ''}>
                          <Button size="small" icon={<CheckCircleOutlined />} onClick={() => handleValidate('python')} loading={validationState.python?.validating}>{t('configPage.validate')}</Button>
                        </Tooltip>
                      </Card>

                      {/* EasyPaper */}
                      <Card
                        size="small"
                        title={
                          <Space>
                            <span>{t('configPage.advanced.easypaper.title')}</span>
                            <Tooltip title={t('configPage.advanced.easypaper.hint')}><QuestionCircleOutlined style={{ color: palette.descriptionForeground }} /></Tooltip>
                          </Space>
                        }
                        style={{
                          marginBottom: 12,
                          borderRadius: 10,
                          border: `1px solid ${palette.panelBorder}`,
                          background: isDark
                            ? 'rgba(37, 37, 38, 0.5)'
                            : 'rgba(255, 255, 255, 0.45)',
                          backdropFilter: 'blur(12px)',
                          WebkitBackdropFilter: 'blur(12px)',
                        }}
                        styles={{ body: { padding: '12px 16px' } }}
                      >
                        <Form.Item name="easypaperApiUrl" label={t('configPage.advanced.easypaper.apiUrl')}>
                          <Input placeholder={t('configPage.advanced.easypaper.apiUrlPlaceholder')} />
                        </Form.Item>
                        <Form.Item name="easypaperLlmApiKey" label={t('configPage.advanced.easypaper.llmApiKey')}>
                          <Input.Password
                            placeholder={t('configPage.linkedPlaceholders.apiKey', {
                              status: hasDefaultLlmKey
                                ? t('configPage.linkedPlaceholders.configured')
                                : t('configPage.linkedPlaceholders.notConfigured'),
                            })}
                            autoComplete="off"
                          />
                        </Form.Item>
                        <Form.Item name="easypaperLlmModel" label={t('configPage.advanced.easypaper.llmModel')}>
                          <Input placeholder={t('configPage.advanced.easypaper.llmModelPlaceholder', { model: defaultLlmModel })} />
                        </Form.Item>
                        <Form.Item name="easypaperVlmModel" label={t('configPage.advanced.easypaper.vlmModel')}>
                          <Input placeholder={t('configPage.advanced.easypaper.vlmModelPlaceholder', { model: defaultLlmModel })} />
                        </Form.Item>
                        <Form.Item name="easypaperVlmApiKey" label={t('configPage.advanced.easypaper.vlmApiKey')}>
                          <Input.Password
                            placeholder={t('configPage.linkedPlaceholders.apiKey', {
                              status: hasDefaultLlmKey
                                ? t('configPage.linkedPlaceholders.configured')
                                : t('configPage.linkedPlaceholders.notConfigured'),
                            })}
                            autoComplete="off"
                          />
                        </Form.Item>
                        {validationState.easypaperVlm.error && <Alert type="error" message={t('configPage.validationFailed')} description={validationState.easypaperVlm.error} style={{ marginBottom: 8, borderRadius: 6 }} />}
                        {validationState.easypaperVlm.valid && <Alert type="success" message={t('configPage.validationSuccess')} style={{ marginBottom: 8, borderRadius: 6 }} />}
                        <Tooltip title={easypaperVlmValidateDisabledReason || ''}>
                          <Button
                            size="small"
                            icon={<CheckCircleOutlined />}
                            onClick={() => handleValidate('easypaperVlm')}
                            loading={validationState.easypaperVlm?.validating}
                            disabled={Boolean(easypaperVlmValidateDisabledReason)}
                          >
                            {t('configPage.validate')}
                          </Button>
                        </Tooltip>
                      </Card>

                      {/* 文献检索 */}
                      <Card
                        size="small"
                        title={
                          <Space>
                            <span>{t('configPage.literature.title')}</span>
                            <Tooltip title={t('configPage.literature.hint')}><QuestionCircleOutlined style={{ color: palette.descriptionForeground }} /></Tooltip>
                          </Space>
                        }
                        style={{
                          marginBottom: 12,
                          borderRadius: 10,
                          border: `1px solid ${palette.panelBorder}`,
                          background: isDark
                            ? 'rgba(37, 37, 38, 0.5)'
                            : 'rgba(255, 255, 255, 0.45)',
                          backdropFilter: 'blur(12px)',
                          WebkitBackdropFilter: 'blur(12px)',
                        }}
                        styles={{ body: { padding: '12px 16px' } }}
                      >
                        <Form.Item name="literatureSearchApiUrl" label={t('configPage.advanced.literature.apiUrl')}>
                          <Input placeholder={t('configPage.advanced.literature.apiUrlPlaceholder')} />
                        </Form.Item>
                        <Form.Item name="literatureSearchApiKey" label="API Key">
                          <Input.Password placeholder="lit-xxx" autoComplete="off" />
                        </Form.Item>
                        <Form.Item>
                          <Space>
                            <Tooltip title={literatureValidateDisabledReason || ''}>
                              <Button
                                size="small"
                                icon={<CheckCircleOutlined />}
                                loading={validationState.literature?.validating}
                                onClick={() => handleValidate('literature')}
                                disabled={Boolean(literatureValidateDisabledReason)}
                              >
                                {t('configPage.literature.validateConfig')}
                              </Button>
                            </Tooltip>
                            {validationState.literature?.valid === true && (
                              <Text type="success">✓ {t('configPage.literature.validateSuccess')}</Text>
                            )}
                            {validationState.literature?.valid === false && (
                              <Text type="danger">✗ {validationState.literature.error}</Text>
                            )}
                          </Space>
                        </Form.Item>
                      </Card>
                    </>
                  ),
                },
              ]}
            />

            {/* ========== 操作按钮 - 玻璃态 ========== */}
            <div
              style={{
                textAlign: 'center',
                padding: '20px',
                borderRadius: 12,
                border: `1px solid ${palette.panelBorder}`,
                background: isDark
                  ? 'rgba(37, 37, 38, 0.6)'
                  : 'rgba(255, 255, 255, 0.5)',
                backdropFilter: 'blur(16px)',
                WebkitBackdropFilter: 'blur(16px)',
                boxShadow: '0 2px 10px rgba(0,0,0,0.06)',
              }}
            >
              <Space size="middle">
                <Button
                  size="large"
                  icon={<ReloadOutlined />}
                  onClick={handleResetDefaults}
                >
                  {t('configPage.resetDefaults')}
                </Button>
                <Button
                  size="large"
                  icon={<SaveOutlined />}
                  onClick={handleSave}
                  disabled={Boolean(defaultValidateDisabledReason)}
                  loading={loading}
                >
                  {t('configPage.save')}
                </Button>
                <Button
                  type="primary"
                  size="large"
                  icon={<RocketOutlined />}
                  onClick={handleSaveAndStart}
                  loading={startingBackend}
                >
                  {startingBackend ? t('configPage.starting') : t('configPage.saveAndStart')}
                </Button>
              </Space>
            </div>
          </Form>
        </Content>
      </Layout>
    </ConfigProvider>
  );
};
