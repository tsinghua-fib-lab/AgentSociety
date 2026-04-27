import * as React from 'react';
import { ConfigProvider, Transfer, Button, Space, Typography, Card, Alert, Spin, Modal, Tag, Layout, Tooltip } from 'antd';
import { SaveOutlined, ReloadOutlined, InfoCircleOutlined, SettingOutlined, RobotOutlined, CloudServerOutlined, AppstoreOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import type { VSCodeAPI, SimSettings, AgentInfo, EnvModuleInfo } from './types';
import { MarkdownRenderer } from '../components/MarkdownRenderer';
import { useVscodeTheme } from '../theme';
import '../i18n';

const { Content } = Layout;
const { Title, Text } = Typography;

// 截取描述预览文本
const getDescriptionPreview = (description: string, maxLength: number = 150): string => {
  if (!description) return '';
  // 移除 markdown 格式标记
  const plainText = description.replace(/[#*`_\[\]()]/g, '').replace(/\n/g, ' ').trim();
  if (plainText.length <= maxLength) return plainText;
  return plainText.substring(0, maxLength) + '...';
};

interface SimSettingsAppProps {
  vscode: VSCodeAPI;
  initialSettings?: SimSettings;
}

export const SimSettingsApp: React.FC<SimSettingsAppProps> = ({
  vscode,
  initialSettings,
}: SimSettingsAppProps) => {
  const { t } = useTranslation();
  const { isDark, palette, themeConfig } = useVscodeTheme();
  const [agentClasses, setAgentClasses] = React.useState<Record<string, AgentInfo>>({});
  const [envModules, setEnvModules] = React.useState<Record<string, EnvModuleInfo>>({});
  const [loading, setLoading] = React.useState<boolean>(true);
  const [agentClassesList, setAgentClassesList] = React.useState<string[]>(
    initialSettings?.agentClasses || []
  );
  const [envModulesList, setEnvModulesList] = React.useState<string[]>(
    initialSettings?.envModules || []
  );
  const [saved, setSaved] = React.useState<boolean>(false);
  const [descriptionModalVisible, setDescriptionModalVisible] = React.useState<boolean>(false);
  const [currentDescription, setCurrentDescription] = React.useState<{ title: string; content: string } | null>(null);

  // 组件挂载时请求数据
  React.useEffect(() => {
    // 请求 agent classes 和 env modules 数据
    vscode.postMessage({
      command: 'requestData',
    });
  }, [vscode]);

  // 监听来自扩展的消息
  React.useEffect(() => {
    const handleMessage = (event: MessageEvent<any>) => {
      const message = event.data;

      if (message.command === 'initialData') {
        // 接收初始数据
        if (message.agentClasses) {
          setAgentClasses(message.agentClasses);
        }
        if (message.envModules) {
          setEnvModules(message.envModules);
        }
        if (message.settings) {
          const settings: SimSettings = message.settings;
          // 更新 agent classes 列表
          if (settings.agentClasses && Array.isArray(settings.agentClasses)) {
            setAgentClassesList(settings.agentClasses);
          } else {
            setAgentClassesList([]);
          }
          // 更新 env modules 列表
          if (settings.envModules && Array.isArray(settings.envModules)) {
            setEnvModulesList(settings.envModules);
          } else {
            setEnvModulesList([]);
          }
        }
        setLoading(false);
      } else if (message.command === 'update') {
        // 更新设置
        try {
          const settings: SimSettings = JSON.parse(message.text || '{}');

          // 更新 agent classes
          if (settings.agentClasses && Array.isArray(settings.agentClasses)) {
            setAgentClassesList(settings.agentClasses);
          } else {
            setAgentClassesList([]);
          }

          // 更新 env modules
          if (settings.envModules && Array.isArray(settings.envModules)) {
            setEnvModulesList(settings.envModules);
          } else {
            setEnvModulesList([]);
          }
        } catch (e) {
          console.error('Error parsing settings:', e);
        }
      }
    };

    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, []);

  const handleSave = () => {
    // 只保存配置相关的字段
    const settings: SimSettings = {
      agentClasses: agentClassesList,
      envModules: envModulesList,
    };

    vscode.postMessage({
      command: 'save',
      content: JSON.stringify(settings, null, 2),
    });

    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const handleLoadDefaults = () => {
    setAgentClassesList([]);
    setEnvModulesList([]);
  };

  const handleViewDescription = (type: string, isAgent: boolean) => {
    const info = isAgent ? agentClasses[type] : envModules[type];
    if (info && info.description) {
      setCurrentDescription({
        title: `${type} (${info.class_name})`,
        content: info.description,
      });
      setDescriptionModalVisible(true);
    }
  };

  const handleCloseDescriptionModal = () => {
    setDescriptionModalVisible(false);
    setCurrentDescription(null);
  };

  // 准备 Transfer 数据源
  const agentDataSource = Object.keys(agentClasses).map(type => ({
    key: type,
    title: type,
    class_name: agentClasses[type].class_name,
    description: agentClasses[type].description || '',
    is_custom: agentClasses[type].is_custom || false,
  }));

  const envModuleDataSource = Object.keys(envModules).map(type => ({
    key: type,
    title: type,
    class_name: envModules[type].class_name,
    description: envModules[type].description || '',
    is_custom: envModules[type].is_custom || false,
  }));

  // 统计卡片样式
  const statPill = (label: string, value: string | number, accent?: string) => (
    <div
      style={{
        flex: '1 1 120px',
        minWidth: 100,
        padding: '12px 16px',
        borderRadius: 8,
        border: `1px solid ${palette.panelBorder}`,
        background: `linear-gradient(135deg, ${palette.surfaceBackground} 0%, ${palette.editorBackground} 100%)`,
        transition: 'all 0.2s ease',
      }}
    >
      <div style={{ fontSize: 11, color: palette.descriptionForeground, marginBottom: 6, fontWeight: 500, letterSpacing: 0.3 }}>{label}</div>
      <div
        style={{
          fontSize: 22,
          fontWeight: 700,
          fontVariantNumeric: 'tabular-nums',
          color: accent ?? palette.editorForeground,
          lineHeight: 1,
        }}
      >
        {value}
      </div>
    </div>
  );

  // 自定义渲染函数 - Agent Classes
  const renderAgentItem = (item: typeof agentDataSource[0]) => {
    const preview = getDescriptionPreview(item.description);
    return (
      <Card
        size="small"
        hoverable={!!item.description}
        style={{
          marginBottom: '8px',
          cursor: item.description ? 'pointer' : 'default',
          backgroundColor: item.is_custom ? palette.surfaceBackground : palette.surfaceMuted,
          borderRadius: 8,
          border: `1px solid ${palette.panelBorder}`,
        }}
        styles={{ body: { padding: '10px 12px' } }}
        onClick={() => {
          if (item.description) {
            handleViewDescription(item.key, true);
          }
        }}
      >
        <Space direction="vertical" size={4} style={{ width: '100%' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <Text strong style={{ fontSize: '13px' }}>
              {item.title}
            </Text>
            <Space size={4}>
              {item.is_custom && (
                <Tag color="blue" style={{ fontSize: '10px', margin: 0, lineHeight: '16px' }}>
                  {t('simSettings.custom') || 'Custom'}
                </Tag>
              )}
              {item.description && (
                <Tooltip title={t('simSettings.agentClasses.viewDescription')}>
                  <InfoCircleOutlined
                    style={{
                      fontSize: '14px',
                      flexShrink: 0,
                      color: palette.linkForeground,
                    }}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleViewDescription(item.key, true);
                    }}
                  />
                </Tooltip>
              )}
            </Space>
          </div>
          <Text type="secondary" style={{ fontSize: '11px', display: 'block' }}>
            {item.class_name}
          </Text>
          {preview && (
            <Text
              type="secondary"
              style={{
                fontSize: '11px',
                display: 'block',
                lineHeight: '1.4',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {preview}
            </Text>
          )}
        </Space>
      </Card>
    );
  };

  // 自定义渲染函数 - Env Modules
  const renderEnvModuleItem = (item: typeof envModuleDataSource[0]) => {
    const preview = getDescriptionPreview(item.description);
    return (
      <Card
        size="small"
        hoverable={!!item.description}
        style={{
          marginBottom: '8px',
          cursor: item.description ? 'pointer' : 'default',
          backgroundColor: item.is_custom ? palette.surfaceBackground : palette.surfaceMuted,
          borderRadius: 8,
          border: `1px solid ${palette.panelBorder}`,
        }}
        styles={{ body: { padding: '10px 12px' } }}
        onClick={() => {
          if (item.description) {
            handleViewDescription(item.key, false);
          }
        }}
      >
        <Space direction="vertical" size={4} style={{ width: '100%' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <Text strong style={{ fontSize: '13px' }}>
              {item.title}
            </Text>
            <Space size={4}>
              {item.is_custom && (
                <Tag color="blue" style={{ fontSize: '10px', margin: 0, lineHeight: '16px' }}>
                  {t('simSettings.custom') || 'Custom'}
                </Tag>
              )}
              {item.description && (
                <Tooltip title={t('simSettings.envModules.viewDescription')}>
                  <InfoCircleOutlined
                    style={{
                      fontSize: '14px',
                      flexShrink: 0,
                      color: palette.linkForeground,
                    }}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleViewDescription(item.key, false);
                    }}
                  />
                </Tooltip>
              )}
            </Space>
          </div>
          <Text type="secondary" style={{ fontSize: '11px', display: 'block' }}>
            {item.class_name}
          </Text>
          {preview && (
            <Text
              type="secondary"
              style={{
                fontSize: '11px',
                display: 'block',
                lineHeight: '1.4',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {preview}
            </Text>
          )}
        </Space>
      </Card>
    );
  };

  // 统计
  const customAgentCount = Object.values(agentClasses).filter(a => a.is_custom).length;
  const customEnvCount = Object.values(envModules).filter(e => e.is_custom).length;

  if (loading) {
    return (
      <ConfigProvider theme={themeConfig}>
        <Layout style={{ minHeight: '100vh', background: 'transparent' }}>
          <Content style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', height: '100vh', gap: 16 }}>
            <Spin size="large" />
            <Text>{t('simSettings.loading')}</Text>
          </Content>
        </Layout>
      </ConfigProvider>
    );
  }

  return (
    <ConfigProvider theme={themeConfig}>
      <Layout style={{ minHeight: '100vh', background: 'transparent' }}>
        <Content style={{ padding: '20px 22px 28px' }}>
          <div style={{ maxWidth: 1180, margin: '0 auto' }}>
            {/* 头部区域 */}
            <div
              style={{
                marginBottom: 20,
                padding: '24px 28px',
                borderRadius: 16,
                border: `1px solid ${palette.panelBorder}`,
                background: `linear-gradient(180deg, ${palette.surfaceBackground} 0%, ${palette.editorBackground} 100%)`,
                boxShadow: '0 2px 8px rgba(0,0,0,0.08)',
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
                      background: `linear-gradient(135deg, ${palette.linkForeground}20 0%, ${palette.linkForeground}10 100%)`,
                      color: palette.linkForeground,
                    }}
                  >
                    <SettingOutlined style={{ fontSize: 20 }} />
                  </span>
                  <div>
                    <Title level={4} style={{ margin: 0 }}>{t('simSettings.title')}</Title>
                    <Text type="secondary" style={{ fontSize: 12 }}>{t('simSettings.description')}</Text>
                  </div>
                </div>
                <Space size="small">
                  <Button icon={<ReloadOutlined />} onClick={handleLoadDefaults} size="small">
                    {t('simSettings.loadDefaults')}
                  </Button>
                  <Button type="primary" icon={<SaveOutlined />} onClick={handleSave} size="small">
                    {t('simSettings.save')}
                  </Button>
                </Space>
              </div>

              {/* 统计卡片 */}
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
                {statPill(t('simSettings.agentClasses.title'), Object.keys(agentClasses).length, palette.linkForeground)}
                {statPill(t('simSettings.envModules.title'), Object.keys(envModules).length, palette.successForeground)}
                {statPill(t('simSettings.custom'), customAgentCount + customEnvCount)}
              </div>
            </div>

            {saved && (
              <Alert
                message={t('simSettings.saved')}
                type="success"
                showIcon
                closable
                style={{ marginBottom: 16 }}
                onClose={() => setSaved(false)}
              />
            )}

            {/* Agent Classes Selection */}
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
                <RobotOutlined style={{ color: palette.linkForeground }} />
                <Text strong style={{ fontSize: 14 }}>{t('simSettings.agentClasses.title')}</Text>
                <Tag color="blue" style={{ marginLeft: 'auto' }}>{agentClassesList.length} / {Object.keys(agentClasses).length}</Tag>
              </div>
              <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 12 }}>
                {t('simSettings.agentClasses.description')}
              </Text>
              <div style={{ width: '100%', overflow: 'hidden' }}>
                <Transfer
                  dataSource={agentDataSource}
                  targetKeys={agentClassesList}
                  onChange={(keys) => setAgentClassesList(keys as string[])}
                  render={(item) => renderAgentItem(item as typeof agentDataSource[0])}
                  showSearch
                  filterOption={(inputValue, item) =>
                    item.title.toLowerCase().includes(inputValue.toLowerCase()) ||
                    item.class_name.toLowerCase().includes(inputValue.toLowerCase()) ||
                    (item.description || '').toLowerCase().includes(inputValue.toLowerCase())
                  }
                  titles={[
                    t('simSettings.agentClasses.available') || 'Available',
                    t('simSettings.agentClasses.selected') || 'Selected',
                  ]}
                  operations={[
                    t('simSettings.add') || 'Add',
                    t('simSettings.remove') || 'Remove',
                  ]}
                  listStyle={{
                    width: 'calc(50% - 80px)',
                    height: 350,
                  }}
                  style={{
                    width: '100%',
                  }}
                />
              </div>
            </Card>

            {/* Environment Modules Selection */}
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
                <CloudServerOutlined style={{ color: palette.successForeground }} />
                <Text strong style={{ fontSize: 14 }}>{t('simSettings.envModules.title')}</Text>
                <Tag color="green" style={{ marginLeft: 'auto' }}>{envModulesList.length} / {Object.keys(envModules).length}</Tag>
              </div>
              <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 12 }}>
                {t('simSettings.envModules.description')}
              </Text>
              <div style={{ width: '100%', overflow: 'hidden' }}>
                <Transfer
                  dataSource={envModuleDataSource}
                  targetKeys={envModulesList}
                  onChange={(keys) => setEnvModulesList(keys as string[])}
                  render={(item) => renderEnvModuleItem(item as typeof envModuleDataSource[0])}
                  showSearch
                  filterOption={(inputValue, item) =>
                    item.title.toLowerCase().includes(inputValue.toLowerCase()) ||
                    item.class_name.toLowerCase().includes(inputValue.toLowerCase()) ||
                    (item.description || '').toLowerCase().includes(inputValue.toLowerCase())
                  }
                  titles={[
                    t('simSettings.envModules.available') || 'Available',
                    t('simSettings.envModules.selected') || 'Selected',
                  ]}
                  operations={[
                    t('simSettings.add') || 'Add',
                    t('simSettings.remove') || 'Remove',
                  ]}
                  listStyle={{
                    width: 'calc(50% - 80px)',
                    height: 350,
                  }}
                  style={{
                    width: '100%',
                  }}
                />
              </div>
            </Card>

            {/* Info Card */}
            <Card
              style={{
                borderRadius: 12,
                border: `1px solid ${palette.panelBorder}`,
                background: palette.surfaceMuted,
                borderLeft: `3px solid ${palette.linkForeground}`,
              }}
              styles={{ body: { padding: '16px 20px' } }}
            >
              <Space direction="vertical" size={8}>
                <Text strong style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <InfoCircleOutlined style={{ color: palette.linkForeground }} />
                  {t('simSettings.note.title')}
                </Text>
                <Text type="secondary" style={{ fontSize: 12, display: 'block' }}>
                  {t('simSettings.note.text1')}
                </Text>
                <Text type="secondary" style={{ fontSize: 12, display: 'block' }}>
                  {t('simSettings.note.text2')}
                </Text>
                <Text type="secondary" style={{ fontSize: 12, display: 'block' }}>
                  {t('simSettings.note.text3')}
                </Text>
              </Space>
            </Card>
          </div>

          {/* Description Modal */}
          <Modal
            title={currentDescription?.title || t('simSettings.descriptionModal.title')}
            open={descriptionModalVisible}
            onCancel={handleCloseDescriptionModal}
            footer={[
              <Button key="close" onClick={handleCloseDescriptionModal}>
                {t('simSettings.close') || 'Close'}
              </Button>,
            ]}
            width={800}
            style={{
              top: 20,
            }}
            styles={{
              body: {
                maxHeight: '70vh',
                overflow: 'auto',
                padding: '24px',
              },
            }}
          >
            {currentDescription?.content ? (
              <MarkdownRenderer
                content={currentDescription.content}
                isDark={isDark}
              />
            ) : (
              <Text type="secondary">{t('simSettings.descriptionModal.noDescription')}</Text>
            )}
          </Modal>
        </Content>
      </Layout>
    </ConfigProvider>
  );
};
