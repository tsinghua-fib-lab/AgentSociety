import * as React from 'react';
import {
  ConfigProvider,
  Card,
  Typography,
  Space,
  Button,
  Table,
  Collapse,
  Tag,
  Input,
  InputNumber,
  Select,
  Spin,
  Alert,
  Empty,
  Popconfirm,
  Layout,
} from 'antd';
import {
  SaveOutlined,
  DeleteOutlined,
  PlusOutlined,
  SettingOutlined,
  UserOutlined,
  EnvironmentOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
} from '@ant-design/icons';
import type { VSCodeAPI, InitConfig, EnvModuleConfig, AgentConfig } from './types';
import { useVscodeTheme } from '../theme';
import { useTranslation } from 'react-i18next';
import '../i18n';

const { Content } = Layout;
const { Title, Text } = Typography;
const { Panel } = Collapse;

interface InitConfigAppProps {
  vscode: VSCodeAPI;
  initialConfig?: InitConfig;
}

// 渲染单个参数的编辑器
const ParamEditor: React.FC<{
  value: any;
  onChange: (value: any) => void;
  depth?: number;
  palette: any;
}> = ({ value, onChange, depth = 0, palette }) => {
  const { t } = useTranslation();
  if (value === null || value === undefined) {
    return <Text type="secondary">null</Text>;
  }

  if (typeof value === 'boolean') {
    return (
      <Select
        value={value}
        onChange={onChange}
        size="small"
        style={{ width: 80 }}
        options={[
          { value: true, label: 'true' },
          { value: false, label: 'false' },
        ]}
      />
    );
  }

  if (typeof value === 'number') {
    return (
      <InputNumber
        value={value}
        onChange={(v) => onChange(v)}
        size="small"
        style={{ width: 120 }}
      />
    );
  }

  if (typeof value === 'string') {
    // 如果字符串较长，使用文本域
    if (value.length > 50) {
      return (
        <Input.TextArea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          size="small"
          autoSize={{ minRows: 2, maxRows: 6 }}
        />
      );
    }
    return (
      <Input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        size="small"
        style={{ width: '100%', maxWidth: 300 }}
      />
    );
  }

  if (Array.isArray(value)) {
    return (
      <div style={{ marginTop: 8 }}>
        {value.map((item, index) => (
          <div key={index} style={{ display: 'flex', gap: 8, marginBottom: 4 }}>
            <ParamEditor
              value={item}
              onChange={(v) => {
                const newArr = [...value];
                newArr[index] = v;
                onChange(newArr);
              }}
              depth={depth + 1}
              palette={palette}
            />
            <Button
              size="small"
              danger
              icon={<DeleteOutlined />}
              onClick={() => onChange(value.filter((_, i) => i !== index))}
            />
          </div>
        ))}
        <Button
          size="small"
          type="dashed"
          icon={<PlusOutlined />}
          onClick={() => onChange([...value, ''])}
        >
          {t('initConfig.add')}
        </Button>
      </div>
    );
  }

  if (typeof value === 'object') {
    const keys = Object.keys(value);
    return (
      <div
        style={{
          paddingLeft: depth > 0 ? 12 : 0,
          borderLeft: depth > 0 ? `2px solid ${palette.panelBorder}` : 'none',
        }}
      >
        {keys.map((key) => (
          <div key={key} style={{ marginBottom: 8 }}>
            <Text strong style={{ marginRight: 8 }}>
              {key}:
            </Text>
            <ParamEditor
              value={value[key]}
              onChange={(v) => onChange({ ...value, [key]: v })}
              depth={depth + 1}
              palette={palette}
            />
          </div>
        ))}
      </div>
    );
  }

  return <Text>{String(value)}</Text>;
};

export const InitConfigApp: React.FC<InitConfigAppProps> = ({ vscode, initialConfig }) => {
  const { t } = useTranslation();
  const { palette, themeConfig } = useVscodeTheme();
  const [config, setConfig] = React.useState<InitConfig>(initialConfig || {});
  const [loading, setLoading] = React.useState<boolean>(true);
  const [saved, setSaved] = React.useState<boolean>(false);

  // 组件挂载时请求数据
  React.useEffect(() => {
    vscode.postMessage({ command: 'requestData' });
  }, [vscode]);

  // 监听来自扩展的消息
  React.useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      const message = event.data;

      if (message.command === 'initialData' || message.command === 'update') {
        let newConfig: InitConfig = {};
        if (message.config) {
          newConfig = message.config;
        } else if (message.text) {
          try {
            newConfig = JSON.parse(message.text);
          } catch (e) {
            console.error('Error parsing config:', e);
          }
        }
        setConfig(newConfig);
        setLoading(false);
      }
    };

    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, []);

  // 保存配置
  const handleSave = () => {
    vscode.postMessage({
      command: 'save',
      content: JSON.stringify(config, null, 2),
    });
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  // 更新环境模块参数
  const updateEnvModule = (index: number, updates: Partial<EnvModuleConfig>) => {
    const newModules = [...(config.env_modules || [])];
    newModules[index] = { ...newModules[index], ...updates };
    setConfig({ ...config, env_modules: newModules });
  };

  // 更新 Agent 参数
  const updateAgent = (index: number, updates: Partial<AgentConfig>) => {
    const newAgents = [...(config.agents || [])];
    newAgents[index] = { ...newAgents[index], ...updates };
    setConfig({ ...config, agents: newAgents });
  };

  // 更新 Agent kwargs
  const updateAgentKwargs = (index: number, key: string, value: any) => {
    const newAgents = [...(config.agents || [])];
    newAgents[index] = {
      ...newAgents[index],
      kwargs: { ...newAgents[index].kwargs, [key]: value },
    };
    setConfig({ ...config, agents: newAgents });
  };

  // 删除环境模块
  const deleteEnvModule = (index: number) => {
    const newModules = (config.env_modules || []).filter((_, i) => i !== index);
    setConfig({ ...config, env_modules: newModules });
  };

  // 删除 Agent
  const deleteAgent = (index: number) => {
    const newAgents = (config.agents || []).filter((_, i) => i !== index);
    setConfig({ ...config, agents: newAgents });
  };

  // 统计卡片
  const statPill = (label: string, value: string | number, icon: React.ReactNode, accent?: string) => (
    <div
      style={{
        flex: '1 1 120px',
        minWidth: 100,
        padding: '14px 18px',
        borderRadius: 10,
        border: `1px solid ${palette.panelBorder}`,
        background: `linear-gradient(135deg, ${palette.surfaceBackground} 0%, ${palette.editorBackground} 100%)`,
        transition: 'all 0.2s ease',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{ color: accent ?? palette.linkForeground }}>{icon}</span>
        <span style={{ fontSize: 11, color: palette.descriptionForeground, fontWeight: 500 }}>{label}</span>
      </div>
      <div style={{ fontSize: 24, fontWeight: 700, color: accent ?? palette.editorForeground, lineHeight: 1 }}>
        {value}
      </div>
    </div>
  );

  if (loading) {
    return (
      <ConfigProvider theme={themeConfig}>
        <Layout style={{ minHeight: '100vh', background: 'transparent' }}>
          <Content className="as-page-content" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', height: '100vh', gap: 16 }}>
            <Spin size="large" />
            <Text>{t('initConfig.loading')}</Text>
          </Content>
        </Layout>
      </ConfigProvider>
    );
  }

  const envModules = config.env_modules || [];
  const agents = config.agents || [];
  const isComplete = envModules.length > 0 && agents.length > 0;

  return (
    <ConfigProvider theme={themeConfig}>
      <Layout style={{ minHeight: '100vh', background: 'transparent' }}>
        <Content className="as-page-content" style={{ padding: '20px 22px 28px' }}>
          <div style={{ maxWidth: 1180, margin: '0 auto' }}>
            {/* 头部区域 */}
            <div
              className="as-page-hero"
              style={{
                marginBottom: 20,
                padding: '24px 28px',
                borderRadius: 16,
                border: `1px solid ${palette.panelBorder}`,
                background: palette.surfaceMuted,

              }}
            >
              <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 16, marginBottom: 20 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <span
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      width: 42,
                      height: 42,
                      borderRadius: 12,
                      background: `color-mix(in srgb, ${palette.linkForeground} 12%, transparent)`,
                      color: palette.linkForeground,
                    }}
                  >
                    <SettingOutlined style={{ fontSize: 20 }} />
                  </span>
                  <div>
                    <Title level={4} style={{ margin: 0 }}>{t('initConfig.title')}</Title>
                    <Text type="secondary" style={{ fontSize: 12 }}>{t('initConfig.subtitle')}</Text>
                  </div>
                </div>
                <Space>
                  <Button onClick={() => setConfig(initialConfig || {})}>
                    {t('initConfig.reset')}
                  </Button>
                  <Button type="primary" icon={<SaveOutlined />} onClick={handleSave}>
                    {t('initConfig.save')}
                  </Button>
                </Space>
              </div>

              {/* 统计卡片 */}
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
                {statPill(t('initConfig.modules'), envModules.length, <EnvironmentOutlined />, palette.linkForeground)}
                {statPill(t('initConfig.agents'), agents.length, <UserOutlined />, palette.successForeground)}
                {statPill(t('initConfig.status'), isComplete ? t('initConfig.complete') : t('initConfig.incomplete'), isComplete ? <CheckCircleOutlined /> : <CloseCircleOutlined />, isComplete ? palette.successForeground : palette.warningForeground)}
              </div>
            </div>

            {saved && (
              <Alert
                message={t('initConfig.saved')}
                type="success"
                showIcon
                closable
                style={{ marginBottom: 16 }}
                onClose={() => setSaved(false)}
              />
            )}

            {/* 环境模块区域 */}
            <Card
              style={{
                marginBottom: 16,
                borderRadius: 12,
                border: `1px solid ${palette.panelBorder}`,
                background: palette.surfaceMuted,
              }}
              styles={{ body: { padding: '16px 20px' } }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
                <EnvironmentOutlined style={{ color: palette.linkForeground }} />
                <Text strong style={{ fontSize: 14 }}>{t('initConfig.moduleConfig')}</Text>
                <Tag color="blue" style={{ marginLeft: 'auto' }}>{envModules.length}</Tag>
              </div>
              {envModules.length === 0 ? (
                <Empty description={t('initConfig.noModules')} style={{ padding: 20 }} />
              ) : (
                <Collapse accordion style={{ background: 'transparent' }}>
                  {envModules.map((module, index) => (
                    <Panel
                      header={
                        <Space>
                          <Tag color="green" style={{ margin: 0 }}>{module.module_type}</Tag>
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            {t('initConfig.parameterCount', { count: Object.keys(module.kwargs || {}).length })}
                          </Text>
                        </Space>
                      }
                      key={index}
                      extra={
                        <Popconfirm
                          title={t('initConfig.removeModule')}
                          onConfirm={() => deleteEnvModule(index)}
                          okText={t('initConfig.confirm')}
                          cancelText={t('initConfig.cancel')}
                        >
                          <Button
                            size="small"
                            danger
                            icon={<DeleteOutlined />}
                            onClick={(e) => e.stopPropagation()}
                          />
                        </Popconfirm>
                      }
                    >
                      <div style={{ padding: '12px 0' }}>
                        <Text strong style={{ display: 'block', marginBottom: 12 }}>
                          {t('initConfig.moduleType', { type: module.module_type })}
                        </Text>
                        <Card
                          size="small"
                          title={t('initConfig.parameters')}
                          style={{
                            borderRadius: 8,
                            background: palette.editorBackground,
                            border: `1px solid ${palette.panelBorder}`,
                          }}
                          styles={{ body: { padding: 12 } }}
                        >
                          <ParamEditor
                            value={module.kwargs}
                            onChange={(newKwargs) => updateEnvModule(index, { kwargs: newKwargs })}
                            palette={palette}
                          />
                        </Card>
                      </div>
                    </Panel>
                  ))}
                </Collapse>
              )}
            </Card>

            {/* Agent 区域 */}
            <Card
              style={{
                marginBottom: 16,
                borderRadius: 12,
                border: `1px solid ${palette.panelBorder}`,
                background: palette.surfaceMuted,
              }}
              styles={{ body: { padding: '16px 20px' } }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
                <UserOutlined style={{ color: palette.successForeground }} />
                <Text strong style={{ fontSize: 14 }}>{t('initConfig.agentConfig')}</Text>
                <Tag color="green" style={{ marginLeft: 'auto' }}>{agents.length}</Tag>
              </div>
              {agents.length === 0 ? (
                <Empty description={t('initConfig.noAgents')} style={{ padding: 20 }} />
              ) : (
                <Table
                  dataSource={agents.map((agent, index) => ({ ...agent, _index: index }))}
                  rowKey="agent_id"
                  pagination={false}
                  size="small"
                  expandable={{
                    expandedRowRender: (record) => (
                      <div style={{ padding: 12 }}>
                        <Card
                          size="small"
                          title={t('initConfig.kwargs')}
                          style={{
                            marginBottom: 12,
                            borderRadius: 8,
                            background: palette.editorBackground,
                            border: `1px solid ${palette.panelBorder}`,
                          }}
                          styles={{ body: { padding: 12 } }}
                        >
                          <ParamEditor
                            value={record.kwargs}
                            onChange={(newKwargs) => updateAgent(record._index, { kwargs: newKwargs })}
                            palette={palette}
                          />
                        </Card>
                        {record.kwargs?.profile && (
                          <Card
                            size="small"
                            title="Profile"
                            style={{
                              borderRadius: 8,
                              background: palette.editorBackground,
                              border: `1px solid ${palette.panelBorder}`,
                            }}
                            styles={{ body: { padding: 12 } }}
                          >
                            <ParamEditor
                              value={record.kwargs.profile}
                              onChange={(newProfile) =>
                                updateAgentKwargs(record._index, 'profile', newProfile)
                              }
                              palette={palette}
                            />
                          </Card>
                        )}
                      </div>
                    ),
                  }}
                  columns={[
                    {
                      title: 'ID',
                      dataIndex: 'agent_id',
                      width: 60,
                    },
                    {
                      title: t('initConfig.type'),
                      dataIndex: 'agent_type',
                      width: 180,
                      render: (text) => <Tag color="blue" style={{ margin: 0 }}>{text}</Tag>,
                    },
                    {
                      title: t('initConfig.name'),
                      dataIndex: ['kwargs', 'name'],
                      render: (text, record) => text || record.kwargs?.profile?.name || '—',
                      ellipsis: true,
                    },
                    {
                      title: t('initConfig.role'),
                      dataIndex: ['kwargs', 'role'],
                      width: 100,
                      render: (text) => text && <Tag style={{ margin: 0 }}>{text}</Tag>,
                    },
                    {
                      title: t('initConfig.actions'),
                      width: 80,
                      render: (_, record) => (
                        <Popconfirm
                          title={t('initConfig.removeAgent')}
                          onConfirm={() => deleteAgent(record._index)}
                          okText={t('initConfig.confirm')}
                          cancelText={t('initConfig.cancel')}
                        >
                          <Button size="small" danger icon={<DeleteOutlined />} />
                        </Popconfirm>
                      ),
                    },
                  ]}
                />
              )}
            </Card>
          </div>
        </Content>
      </Layout>
    </ConfigProvider>
  );
};
