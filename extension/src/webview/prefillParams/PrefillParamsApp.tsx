import * as React from 'react';
import { ConfigProvider, Input, Card, Typography, Spin, Alert, Empty, Space, Badge, Tabs, Tag, Button, Tooltip } from 'antd';
import {
  SearchOutlined, ReloadOutlined, PlayCircleOutlined, CheckCircleOutlined, CloseCircleOutlined, LoadingOutlined,
  FileTextOutlined, AppstoreOutlined, DatabaseOutlined, SettingOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import type { VSCodeAPI, ClassInfo, AvailableClasses, PrefillParams } from './types';
import { MarkdownRenderer } from '../components/MarkdownRenderer';
import { JsonViewer } from '../components/JsonViewer';
import { useVscodeTheme } from '../theme';
import '../i18n';

const { Title, Text, Paragraph } = Typography;
const { Search } = Input;

interface PrefillParamsAppProps {
  vscode: VSCodeAPI;
}

interface ClassItem {
  type: string;
  kind: 'env_module' | 'agent';
  info: ClassInfo;
  params: Record<string, any>;
}

type TestStatus = 'idle' | 'testing' | 'success' | 'error';

export const PrefillParamsApp: React.FC<PrefillParamsAppProps> = ({ vscode }) => {
  const { t } = useTranslation();
  const { isDark, palette, themeConfig } = useVscodeTheme();
  const [loading, setLoading] = React.useState<boolean>(true);
  const [error, setError] = React.useState<string | null>(null);
  const [classes, setClasses] = React.useState<ClassItem[]>([]);
  const [filteredClasses, setFilteredClasses] = React.useState<ClassItem[]>([]);
  const [selectedClass, setSelectedClass] = React.useState<ClassItem | null>(null);
  const [searchText, setSearchText] = React.useState<string>('');
  const [activeTab, setActiveTab] = React.useState<'env_module' | 'agent'>('env_module');

  // 为每个模块维护测试状态，key 为 `${kind}-${type}`
  const [testStatuses, setTestStatuses] = React.useState<Record<string, TestStatus>>({});
  const [testResults, setTestResults] = React.useState<Record<string, string>>({});

  // 组件挂载时请求数据
  React.useEffect(() => {
    vscode.postMessage({
      command: 'requestData',
    });
  }, [vscode]);

  // 监听来自扩展的消息
  React.useEffect(() => {
    const handleMessage = (event: MessageEvent<any>) => {
      const message = event.data;

      if (message.command === 'initialData') {
        try {
          const classesData: AvailableClasses = message.classes;
          const prefillParams: PrefillParams = message.prefillParams;

          const classItems: ClassItem[] = [];

          Object.entries(classesData.env_modules).forEach(([type, info]) => {
            classItems.push({
              type,
              kind: 'env_module',
              info,
              params: prefillParams.env_modules[type] || {},
            });
          });

          Object.entries(classesData.agents).forEach(([type, info]) => {
            classItems.push({
              type,
              kind: 'agent',
              info,
              params: prefillParams.agents[type] || {},
            });
          });

          setClasses(classItems);
          setLoading(false);
          setError(null);
        } catch (e) {
          console.error('Error processing initial data:', e);
          setError(t('prefillParams.errorMessages.loadFailed'));
          setLoading(false);
          setClasses([]);
          setFilteredClasses([]);
          setSelectedClass(null);
        }
      } else if (message.command === 'error') {
        setError(message.error || t('prefillParams.errorMessages.loadFailed'));
        setLoading(false);
        setClasses([]);
        setFilteredClasses([]);
        setSelectedClass(null);
      } else if (message.command === 'testResult') {
        const moduleKey = message.moduleKey;
        if (moduleKey) {
          setTestStatuses(prev => ({
            ...prev,
            [moduleKey]: message.success ? 'success' : 'error',
          }));
          setTestResults(prev => ({
            ...prev,
            [moduleKey]: message.output || message.error || '',
          }));
        }
      }
    };

    window.addEventListener('message', handleMessage);
    return () => {
      window.removeEventListener('message', handleMessage);
    };
  }, [vscode, t]);

  // 搜索过滤和Tab切换
  React.useEffect(() => {
    let filtered = classes;

    filtered = filtered.filter(item => item.kind === activeTab);

    if (searchText.trim()) {
      const lowerSearch = searchText.toLowerCase();
      filtered = filtered.filter((item) => {
        return (
          item.type.toLowerCase().includes(lowerSearch) ||
          item.info.class_name.toLowerCase().includes(lowerSearch) ||
          item.info.description.toLowerCase().includes(lowerSearch)
        );
      });
    }

    setFilteredClasses(filtered);

    if (selectedClass && selectedClass.kind !== activeTab) {
      setSelectedClass(null);
    }
  }, [searchText, classes, activeTab, selectedClass]);

  const handleRefresh = () => {
    setLoading(true);
    setError(null);
    setClasses([]);
    setFilteredClasses([]);
    setSelectedClass(null);
    vscode.postMessage({
      command: 'refresh',
    });
  };

  const handleOpenPrefillJson = () => {
    vscode.postMessage({ command: 'openPrefillParamsJson' });
  };

  const handleClassSelect = (item: ClassItem) => {
    setSelectedClass(item);
  };

  const handleTestModule = (item: ClassItem) => {
    const key = `${item.kind}-${item.type}`;
    setTestStatuses(prev => ({ ...prev, [key]: 'testing' }));
    setTestResults(prev => ({ ...prev, [key]: '' }));

    vscode.postMessage({
      command: 'testCustomModule',
      moduleKey: key,
      moduleType: item.kind,
      moduleTypeValue: item.type,
      moduleClassName: item.info.class_name,
    });
  };

  const getTestIcon = (status: TestStatus) => {
    switch (status) {
      case 'testing':
        return <LoadingOutlined style={{ color: palette.buttonBackground }} />;
      case 'success':
        return <CheckCircleOutlined style={{ color: palette.successForeground }} />;
      case 'error':
        return <CloseCircleOutlined style={{ color: palette.errorForeground }} />;
      default:
        return null;
    }
  };

  // 统计卡片
  const statPill = (label: string, value: string | number, accent?: string) => (
    <div
      style={{
        flex: '1 1 80px',
        minWidth: 70,
        padding: '8px 12px',
        borderRadius: 6,
        border: `1px solid ${palette.panelBorder}`,
        background: `linear-gradient(135deg, ${palette.surfaceBackground} 0%, ${palette.editorBackground} 100%)`,
      }}
    >
      <div style={{ fontSize: 10, color: palette.descriptionForeground, marginBottom: 2, fontWeight: 500 }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 700, color: accent ?? palette.editorForeground, lineHeight: 1 }}>{value}</div>
    </div>
  );

  if (loading) {
    return (
      <ConfigProvider theme={themeConfig}>
        <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', height: '100vh', gap: 16, backgroundColor: palette.editorBackground }}>
          <Spin size="large" />
          <Text>{t('prefillParams.loading')}</Text>
        </div>
      </ConfigProvider>
    );
  }

  if (error) {
    return (
      <ConfigProvider theme={themeConfig}>
        <div style={{ padding: 20, height: '100vh', backgroundColor: palette.editorBackground }}>
          <Alert
            message={t('prefillParams.error')}
            description={error}
            type="error"
            showIcon
            action={
              <Button icon={<ReloadOutlined />} onClick={handleRefresh}>
                {t('prefillParams.refresh')}
              </Button>
            }
          />
        </div>
      </ConfigProvider>
    );
  }

  const customCount = classes.filter(c => c.info.is_custom).length;
  const builtinCount = classes.length - customCount;
  const envModuleCount = classes.filter(c => c.kind === 'env_module').length;
  const agentCount = classes.filter(c => c.kind === 'agent').length;

  return (
    <ConfigProvider theme={themeConfig}>
      <div
        style={{
          height: '100vh',
          display: 'flex',
          flexDirection: 'column',
          backgroundColor: palette.editorBackground,
          color: palette.editorForeground,
          overflow: 'hidden',
        }}
      >
        {/* 头部区域 - 固定高度 */}
        <div
          style={{
            padding: '12px 16px',
            borderBottom: `1px solid ${palette.panelBorder}`,
            flexShrink: 0,
          }}
        >
          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 10, marginBottom: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  width: 32,
                  height: 32,
                  borderRadius: 8,
                  background: `linear-gradient(135deg, ${palette.linkForeground}20 0%, ${palette.linkForeground}10 100%)`,
                  color: palette.linkForeground,
                }}
              >
                <DatabaseOutlined style={{ fontSize: 14 }} />
              </span>
              <div>
                <Title level={5} style={{ margin: 0 }}>{t('prefillParams.groupTitle')}</Title>
              </div>
            </div>
            <Space size="small">
              <Button size="small" icon={<FileTextOutlined />} onClick={handleOpenPrefillJson}>
                {t('prefillParams.openConfigFile')}
              </Button>
              <Button size="small" icon={<ReloadOutlined />} onClick={handleRefresh}>
                {t('prefillParams.refresh')}
              </Button>
            </Space>
          </div>

          {/* 统计卡片 */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {statPill(t('prefillParams.classInfo.envModule'), envModuleCount, palette.linkForeground)}
            {statPill(t('prefillParams.classInfo.agent'), agentCount, palette.successForeground)}
            {statPill(t('prefillParams.classInfo.builtin'), builtinCount)}
            {statPill(t('prefillParams.classInfo.custom'), customCount)}
          </div>
        </div>

        {/* Tabs 区域 - 固定高度 */}
        <div style={{ flexShrink: 0, padding: '0 16px', background: palette.editorBackground }}>
          <Tabs
            activeKey={activeTab}
            onChange={(key) => {
              setActiveTab(key as 'env_module' | 'agent');
              setSelectedClass(null);
            }}
            style={{ marginBottom: 0 }}
            items={[
              {
                key: 'env_module',
                label: (
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                    <AppstoreOutlined />
                    {t('prefillParams.classInfo.envModule')}
                    <Tag style={{ margin: 0, fontSize: 11 }}>{envModuleCount}</Tag>
                  </span>
                ),
              },
              {
                key: 'agent',
                label: (
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                    <SettingOutlined />
                    {t('prefillParams.classInfo.agent')}
                    <Tag style={{ margin: 0, fontSize: 11 }}>{agentCount}</Tag>
                  </span>
                ),
              },
            ]}
          />
        </div>

        {/* 主内容区 - 自适应剩余高度 */}
        <div style={{ flex: 1, overflow: 'hidden', padding: '8px 16px 12px' }}>
          <div style={{ height: '100%', display: 'flex', gap: 12 }}>
            {/* 左侧列表 */}
            <div
              style={{
                width: 280,
                flexShrink: 0,
                display: 'flex',
                flexDirection: 'column',
                height: '100%',
              }}
            >
              <Search
                placeholder={t('prefillParams.searchPlaceholder')}
                allowClear
                prefix={<SearchOutlined />}
                value={searchText}
                onChange={(e) => setSearchText(e.target.value)}
                style={{ marginBottom: 8, flexShrink: 0 }}
              />
              <div
                style={{
                  flex: 1,
                  overflowY: 'auto',
                  padding: '2px',
                }}
              >
                {filteredClasses.length === 0 ? (
                  <Empty description={t('prefillParams.noClasses')} style={{ marginTop: 20, padding: 10 }} />
                ) : (
                  filteredClasses.map((item) => {
                    const key = `${item.kind}-${item.type}`;
                    const testStatus = testStatuses[key] || 'idle';
                    const testResult = testResults[key];
                    const isCustom = item.info.is_custom;
                    const isSelected = selectedClass?.type === item.type && selectedClass?.kind === item.kind;

                    return (
                      <Card
                        key={key}
                        size="small"
                        style={{
                          marginBottom: 6,
                          cursor: 'pointer',
                          borderRadius: 8,
                          border: isSelected ? `2px solid ${palette.linkForeground}` : `1px solid ${palette.panelBorder}`,
                          backgroundColor: isSelected ? palette.surfaceBackground : palette.surfaceMuted,
                          boxShadow: isSelected ? `0 2px 6px ${palette.linkForeground}20` : 'none',
                          transition: 'all 0.15s ease',
                        }}
                        styles={{ body: { padding: '8px 10px' } }}
                        onClick={() => handleClassSelect(item)}
                        hoverable
                      >
                        <Space direction="vertical" size={3} style={{ width: '100%' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <Space size={4}>
                              <Badge status={item.info.has_prefill ? 'success' : 'default'} />
                              <Text strong style={{ fontSize: 12 }}>{item.type}</Text>
                            </Space>
                            <Tag color={isCustom ? 'blue' : 'default'} style={{ fontSize: 10, margin: 0, lineHeight: '14px' }}>
                              {isCustom ? t('prefillParams.classInfo.custom') : t('prefillParams.classInfo.builtin')}
                            </Tag>
                          </div>
                          <Text
                            type="secondary"
                            style={{ fontSize: 10, display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                            title={item.info.class_name}
                          >
                            {item.info.class_name}
                          </Text>

                          {/* 自定义模块显示测试按钮和状态 */}
                          {isCustom && (
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 2 }}>
                              <Button
                                size="small"
                                icon={<PlayCircleOutlined />}
                                loading={testStatus === 'testing'}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleTestModule(item);
                                }}
                              >
                                {t('prefillParams.classInfo.test')}
                              </Button>
                              {getTestIcon(testStatus)}
                            </div>
                          )}

                          {testStatus !== 'idle' && testResult && (
                            <Alert
                              message={testStatus === 'success' ? t('prefillParams.test.success') : t('prefillParams.test.failed')}
                              description={
                                <Text style={{ fontSize: 10, display: 'block', maxHeight: 40, overflow: 'auto', whiteSpace: 'pre-wrap' }}>
                                  {testResult}
                                </Text>
                              }
                              type={testStatus === 'success' ? 'success' : 'error'}
                              showIcon
                              style={{ padding: '3px 6px', fontSize: 10, marginTop: 3 }}
                            />
                          )}

                          {item.info.has_prefill && (
                            <Text type="success" style={{ fontSize: 10 }}>
                              {t('prefillParams.classInfo.hasPrefill')}
                            </Text>
                          )}
                        </Space>
                      </Card>
                    );
                  })
                )}
              </div>
            </div>

            {/* 右侧详情 */}
            <div
              style={{
                flex: 1,
                minWidth: 0,
                height: '100%',
                overflow: 'hidden',
              }}
            >
              <Card
                style={{
                  borderRadius: 10,
                  border: `1px solid ${palette.panelBorder}`,
                  background: palette.surfaceMuted,
                  height: '100%',
                  display: 'flex',
                  flexDirection: 'column',
                }}
                styles={{ body: { padding: '16px 20px', flex: 1, overflow: 'auto' } }}
              >
                {selectedClass ? (
                  <div>
                    <Space style={{ marginBottom: 10 }}>
                      <Title level={5} style={{ margin: 0 }}>
                        {selectedClass.type}
                      </Title>
                      <Badge status={selectedClass.info.has_prefill ? 'success' : 'default'} />
                      <Tag color={selectedClass.info.is_custom ? 'blue' : 'default'}>
                        {selectedClass.info.is_custom ? t('prefillParams.classInfo.custom') : t('prefillParams.classInfo.builtin')}
                      </Tag>
                    </Space>
                    <Paragraph style={{ marginBottom: 6 }}>
                      <Text strong>{t('prefillParams.classInfo.className')}: </Text>
                      <Text code>{selectedClass.info.class_name}</Text>
                    </Paragraph>
                    <Paragraph style={{ marginBottom: 6 }}>
                      <Text strong>{t('prefillParams.classInfo.kind')}: </Text>
                      <Text>
                        {selectedClass.kind === 'env_module'
                          ? t('prefillParams.classInfo.envModule')
                          : t('prefillParams.classInfo.agent')}
                      </Text>
                    </Paragraph>
                    <div style={{ marginTop: 12 }}>
                      <Text strong style={{ display: 'block', marginBottom: 6 }}>{t('prefillParams.classInfo.description')}</Text>
                      <div style={{
                        padding: 10,
                        borderRadius: 6,
                        background: palette.editorBackground,
                        border: `1px solid ${palette.panelBorder}`,
                      }}>
                        <MarkdownRenderer content={selectedClass.info.description} isDark={isDark} />
                      </div>
                    </div>
                    <div style={{ marginTop: 16 }}>
                      <Title level={5}>{t('prefillParams.classInfo.prefillParams')}</Title>
                      {Object.keys(selectedClass.params).length === 0 ? (
                        <Alert message={t('prefillParams.classInfo.noPrefillParams')} type="info" showIcon style={{ marginTop: 6 }} />
                      ) : (
                        <div style={{ marginTop: 6 }}>
                          <JsonViewer
                            data={selectedClass.params}
                            isDark={isDark}
                            showCopy={true}
                            showExpandCollapse={true}
                            defaultExpandDepth={3}
                            maxHeight="300px"
                          />
                        </div>
                      )}
                    </div>
                  </div>
                ) : (
                  <Empty description={t('prefillParams.selectClass')} style={{ marginTop: 60 }} />
                )}
              </Card>
            </div>
          </div>
        </div>
      </div>
    </ConfigProvider>
  );
};
