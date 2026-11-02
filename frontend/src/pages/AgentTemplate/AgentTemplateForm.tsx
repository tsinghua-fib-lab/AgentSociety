import React, { useState, useEffect, useContext } from 'react';
import { Form, Input, Card, Row, Col, Button, Switch, InputNumber, Select, Space, message, Tooltip, Table, Tabs, Empty } from 'antd';
import { useNavigate, useParams } from 'react-router';
import { fetchCustom } from '../../components/fetch';
import { QuestionCircleOutlined } from '@ant-design/icons';
import MonacoPromptEditor from '../../components/MonacoPromptEditor';
import { useTranslation } from 'react-i18next';
import { observer } from 'mobx-react-lite';
import { AgentTemplateStoreContext } from './agentTemplateStore';
import {
  ApiDistributionType,
  ApiParam,
  ApiNameTypeDescription,
  BlockContextInfo,
  BlockInfo,
  ApiDistributionConfig,
  ApiAgentTemplate,
} from '../../types/agentTemplate';
import { profiles } from './profile';

// ==================== 工具函数 ====================
type MonacoSuggestion = {
  label: string;
  detail?: string;
  children?: MonacoSuggestion[];
};

interface ProfileFormValue {
  type: ApiDistributionType;
  choices?: string[];
  weights?: number[];
  min_value?: number;
  max_value?: number;
  mean?: number;
  std?: number;
}

interface AgentTemplateFormValues {
  name?: string;
  description?: string;
  agent_type?: string;
  agent_class?: string;
  profile?: Record<string, ProfileFormValue>;
  agent_params?: Record<string, unknown>;
  blocks?: Record<string, { params?: Record<string, unknown> }>;
}

const renderDynamicFormItem = (
  paramName: string,
  paramInfo: ApiParam,
  formItemProps: {
    name: (string | number)[],
    suggestions?: MonacoSuggestion[],
  }
) => {
  const baseProps = {
    name: formItemProps.name,
    label: (
      <Space>
        {paramName}
        <Tooltip title={paramInfo.description || ''}>
          <QuestionCircleOutlined />
        </Tooltip>
      </Space>
    ),
    initialValue: paramInfo.default,
    rules: [{ required: paramInfo.required, message: `请输入${paramName}` }]
  };

  switch (paramInfo.type.toLowerCase()) {
    case 'bool':
      return (
        <Form.Item {...baseProps} valuePropName="checked">
          <Switch defaultChecked={paramInfo.default === true} />
        </Form.Item>
      );
    case 'int':
    case 'float':
      return (
        <Form.Item {...baseProps}>
          <InputNumber
            style={{ width: '100%' }}
            step={paramInfo.type === 'int' ? 1 : 0.1}
          />
        </Form.Item>
      );
    case 'str':
      return (
        <Form.Item {...baseProps}>
          <MonacoPromptEditor
            height="200px"
            suggestions={formItemProps.suggestions}
            editorId={paramName}
            key={`${paramName}-${formItemProps.suggestions?.length}`}
          />
        </Form.Item>
      );
    case 'select':
      return (
        <Form.Item {...baseProps}>
          <Select options={paramInfo.options} />
        </Form.Item>
      );
    case 'select_multiple':
      return (
        <Form.Item {...baseProps}>
          <Select mode="multiple" options={paramInfo.options} />
        </Form.Item>
      );
    default:
      return (
        <Form.Item {...baseProps}>
          <Input />
        </Form.Item>
      );
  }
};

// ==================== 组件 ====================
const AgentConfiguration: React.FC = observer(() => {
  const { t } = useTranslation();
  const agentTemplateStore = useContext(AgentTemplateStoreContext);

  if (!agentTemplateStore.agentParam) {
    return (
      <Card title={t('template.agentConfig')} variant="borderless" style={{ marginBottom: '12px' }}>
        <Empty
          description={t('template.selectAgentTypeAndClass')}
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        />
      </Card>
    );
  }

  const { agentParam, suggestions } = agentTemplateStore;

  return (
    <Card title={t('template.agentConfig')} variant="borderless" style={{ marginBottom: '12px' }}>
      <Row gutter={[12, 12]}>
        {agentParam.params_type.map((paramInfo) => (
          <Col
            key={paramInfo.name}
            span={paramInfo.name.toLowerCase().includes('prompt') ? 24 : 12}
          >
            {renderDynamicFormItem(
              paramInfo.name,
              paramInfo,
              {
                name: ['agent_params', paramInfo.name],
                suggestions
              }
            )}
          </Col>
        ))}
      </Row>
    </Card>
  );
});

const BlockConfiguration: React.FC<{
  onBlockContextChange?: (contexts: BlockContextInfo[]) => void;
  selectedBlocks: string[];
  onSelectedBlocksChange: (blocks: string[]) => void;
}> = observer(({ onBlockContextChange, selectedBlocks, onSelectedBlocksChange }) => {
  const [blocks, setBlocks] = useState<BlockInfo[]>([]);
  const [blockParams, setBlockParams] = useState<Record<string, ApiParam[]>>({});
  const [blockContexts, setBlockContexts] = useState<Record<string, ApiNameTypeDescription[]>>({});
  const [blockSuggestions, setBlockSuggestions] = useState<Record<string, MonacoSuggestion[]>>({});
  const { t } = useTranslation();
  const agentTemplateStore = useContext(AgentTemplateStoreContext);

  const generateBlockSuggestions = (blockName: string, blockContext: ApiNameTypeDescription[]) => {
    const blockContextSuggestions = blockContext.map((value) => ({
      label: value.name,
      detail: `[${blockName}] ${value.description || `Type: ${value.type}`}`
    }));

    return agentTemplateStore.suggestions.map(group => {
      if (group.label === 'context') {
        return {
          ...group,
          children: [...(group.children || []), ...blockContextSuggestions]
        };
      }
      return group;
    });
  };

  const fetchBlockParams = async (blockType: string) => {
    try {
      const response = await fetchCustom(`/api/block-param/${blockType}`);
      const data = await response.json();
      if (data.data) {
        setBlockParams(prev => ({
          ...prev,
          [blockType]: data.data.params_type
        }));

        const blockContext = data.data.context || [];
        setBlockContexts(prev => ({
          ...prev,
          [blockType]: blockContext
        }));

        setBlockSuggestions(prev => ({
          ...prev,
          [blockType]: generateBlockSuggestions(blockType, blockContext)
        }));

        const newContexts = selectedBlocks.map(block => ({
          blockName: block,
          context: blockContexts[block] || []
        }));
        onBlockContextChange?.(newContexts);
      }
    } catch (err) {
      console.error(`Failed to fetch params for block ${blockType}:`, err);
    }
  };

  const handleBlockSelect = (values: string[]) => {
    onSelectedBlocksChange(values);

    const newBlocks = values.filter(block => !blockParams[block]);
    newBlocks.forEach(block => {
      fetchBlockParams(block);
    });

    const selectedContexts = values.map(block => ({
      blockName: block,
      context: blockContexts[block] || []
    }));
    onBlockContextChange?.(selectedContexts);
  };

  useEffect(() => {
    fetchCustom('/api/agent-blocks')
      .then(res => res.json())
      .then(response => {
        if (response.data && Array.isArray(response.data)) {
          const blockInfos = response.data.map((blockName: string) => ({
            block_name: blockName,
            description: '',
          }));
          setBlocks(blockInfos);
        }
      })
      .catch(err => {
        console.error('Failed to fetch blocks:', err);
        setBlocks([]);
      });
  }, []);

  return (
    <Card title={t('template.blockConfig')} bordered={false}>
      <Space direction="vertical" style={{ width: '100%' }} size="small">
        <Form.Item
          label={t('template.selectBlocks')}
          style={{ marginBottom: '8px' }}
        >
          <Select
            mode="multiple"
            placeholder={t('template.selectBlocksPlaceholder')}
            style={{ width: '100%' }}
            onChange={handleBlockSelect}
            options={blocks.map(block => ({
              label: block.block_name,
              value: block.block_name
            }))}
          />
        </Form.Item>

        {selectedBlocks.map(blockName => {
          const blockInfo = blocks.find(b => b.block_name === blockName);
          const params = blockParams[blockName];

          if (!blockInfo) return null;

          return (
            <Card
              key={blockName}
              title={blockInfo.block_name}
              size="small"
              style={{ marginBottom: '8px' }}
            >
              {params && params.length > 0 ? (
                params.map((paramInfo) => (
                  <div key={paramInfo.name}>
                    {renderDynamicFormItem(
                      paramInfo.name,
                      paramInfo,
                      {
                        name: ['blocks', blockName, 'params', paramInfo.name],
                        suggestions: blockSuggestions[blockName]
                      }
                    )}
                  </div>
                ))
              ) : (
                <div style={{ padding: '8px', color: '#999', textAlign: 'center' }}>
                  {t('template.noConfigurableParameters')}
                </div>
              )}
            </Card>
          );
        })}
      </Space>
    </Card>
  );
});

const AgentInfoSidebar: React.FC<{ blockContexts?: BlockContextInfo[] }> = observer(({ blockContexts = [] }) => {
  const { t } = useTranslation();
  const agentTemplateStore = useContext(AgentTemplateStoreContext);

  if (!agentTemplateStore.agentParam) {
    return (
      <Tabs defaultActiveKey="context" size="small">
        <Tabs.TabPane tab="Profile" key="profile">
          <Empty
            description={t('template.selectAgentTypeAndClass')}
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          />
        </Tabs.TabPane>
        <Tabs.TabPane tab="Context" key="context">
          <Empty
            description={t('template.selectAgentTypeAndClass')}
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          />
        </Tabs.TabPane>
        <Tabs.TabPane tab="Status" key="status">
          <Empty
            description={t('template.selectAgentTypeAndClass')}
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          />
        </Tabs.TabPane>
      </Tabs>
    );
  }

  const { agentParam: agentInfo } = agentTemplateStore;

  const commonColumns = [
    { title: t('template.sidebar.name'), dataIndex: 'name', width: '25%' },
    { title: t('template.sidebar.type'), dataIndex: 'type', width: '25%' },
    { title: t('template.sidebar.description'), dataIndex: 'description', width: '50%', render: (text: string) => text || '-' }
  ];

  return (
    <Tabs defaultActiveKey="context" size="small">
      <Tabs.TabPane tab="Profile" key="profile">
        <Table
          size="small"
          pagination={false}
          dataSource={profiles}
          columns={[
            { title: t('template.sidebar.name'), dataIndex: 'name', width: '20%' },
            { title: t('template.sidebar.type'), dataIndex: 'type', width: '20%' },
            { title: t('template.sidebar.description'), dataIndex: 'description', width: '40%', render: (text) => text || '-' },
          ]}
        />
      </Tabs.TabPane>
      <Tabs.TabPane tab="Context" key="context">
        <Space direction="vertical" style={{ width: '100%' }} size="small">
          <Card size="small" title="Agent Context" style={{ marginBottom: '8px' }}>
            <Table
              size="small"
              pagination={false}
              dataSource={agentInfo.context.map((value) => ({
                key: value.name,
                name: value.name,
                type: value.type,
                description: value.description,
                default: JSON.stringify(value.default)
              }))}
              columns={commonColumns}
              style={{ overflow: 'auto' }}
            />
          </Card>

          {blockContexts.map(({ blockName, context }) => (
            <Card size="small" title={`${blockName} Context`} key={blockName} style={{ marginBottom: '8px' }}>
              <Table
                size="small"
                pagination={false}
                dataSource={context.map((value) => ({
                  key: value.name,
                  name: value.name,
                  type: value.type,
                  description: value.description,
                  default: JSON.stringify(value.default)
                }))}
                columns={commonColumns}
              />
            </Card>
          ))}
        </Space>
      </Tabs.TabPane>
      <Tabs.TabPane tab="Status" key="status">
        <Table
          size="small"
          pagination={false}
          dataSource={agentInfo.status_attributes.map(attr => ({
            key: attr.name,
            ...attr,
            default: JSON.stringify(attr.default)
          }))}
          columns={[
            { title: t('template.sidebar.name'), dataIndex: 'name', width: '20%' },
            { title: t('template.sidebar.type'), dataIndex: 'type', width: '20%' },
            { title: t('template.sidebar.description'), dataIndex: 'description', width: '40%', render: (text) => text || '-' },
          ]}
        />
      </Tabs.TabPane>
    </Tabs>
  );
});

// ==================== 主组件 ====================
const AgentTemplateForm: React.FC = observer(() => {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const navigate = useNavigate();
  const { id } = useParams();
  const agentTemplateStore = useContext(AgentTemplateStoreContext);
  const [selectedBlocks, setSelectedBlocks] = useState<string[]>([]);

  const agentTypeOptions = [
    { value: 'citizen', label: t('template.agentTypes.citizen') },
    { value: 'supervisor', label: t('template.agentTypes.supervisor') },
  ];

  useEffect(() => {
    const fetch = async () => {
      if (id) {
        const template = await agentTemplateStore.fetchTemplateById(id);
        if (template) {
          form.setFieldsValue({
            name: template.name,
            description: template.description,
            agent_type: template.agent_type,
            agent_class: template.agent_class,
            profile: template.agent_type === 'citizen' ? template.memory_distributions : {},
            agent_params: template.agent_params,
            blocks: template.blocks
          });
          // 初始化选中的blocks
          if (template.blocks) {
            setSelectedBlocks(Object.keys(template.blocks));
          }
        }
      } else {
        form.setFieldsValue({
          description: '',
          profile: {},
        });
        setSelectedBlocks([]);
      }
    }
    fetch();
  }, [id, agentTemplateStore, form]);

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields() as AgentTemplateFormValues;

      // 构造 memory_distributions
      const memory_distributions: Record<string, ApiDistributionConfig> = {};
      if (values.agent_type === 'citizen') {
        Object.entries(values.profile || {}).forEach(([key, value]: [string, ProfileFormValue]) => {
          if (value.type === ApiDistributionType.CHOICE) {
            memory_distributions[key] = {
              type: ApiDistributionType.CHOICE,
              choices: value.choices,
              weights: value.weights
            };
          } else if (value.type === ApiDistributionType.UNIFORM_INT) {
            memory_distributions[key] = {
              type: ApiDistributionType.UNIFORM_INT,
              min_value: value.min_value,
              max_value: value.max_value
            };
          } else if (value.type === ApiDistributionType.NORMAL) {
            memory_distributions[key] = {
              type: ApiDistributionType.NORMAL,
              mean: value.mean,
              std: value.std
            };
          }
        });
      }

      // 构造 agent_params
      const agent_params: Record<string, unknown> = {};
      agentTemplateStore.agentParam.params_type.forEach(paramInfo => {
        const value = values.agent_params?.[paramInfo.name];
        agent_params[paramInfo.name] = value ?? paramInfo.default;
      });

      // 构造 blocks
      const blocksData: Record<string, Record<string, unknown>> = {};
      // 确保所有选中的block都被包含，即使没有参数
      selectedBlocks.forEach(blockName => {
        if (values.blocks && values.blocks[blockName]) {
          blocksData[blockName] = values.blocks[blockName].params || {};
        } else {
          // 如果block没有参数配置，创建空对象
          blocksData[blockName] = {};
        }
      });

      const templateData: Omit<ApiAgentTemplate, 'id' | 'created_at' | 'updated_at'> = {
        name: values.name || 'Default Template Name',
        description: values.description || '',
        agent_type: values.agent_type,
        agent_class: values.agent_class,
        memory_distributions,
        agent_params,
        blocks: blocksData
      };

      await agentTemplateStore.createTemplate(templateData);
      message.success(t('template.messages.createSuccess'));
      navigate('/agent-templates');
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : JSON.stringify(error);
      message.error(errorMessage || t('template.messages.createFailed'));
    }
  };

  return (
    <div style={{ padding: '16px' }}>
      <Card
        title={id ? t('template.editTitle') : t('template.createTitle')}
        extra={
          <Space>
            <Button onClick={() => navigate('/agent-templates')}>{t('common.cancel')}</Button>
            <Button type="primary" onClick={() => form.submit()}>
              {t('common.submit')}
            </Button>
          </Space>
        }
        styles={{
          body: {
            padding: '16px 0'
          }
        }}
      >
        <Form form={form} layout="vertical" onFinish={handleSubmit}>
          <Row gutter={0}>
            <Col span={24} style={{ padding: '0 16px', marginBottom: '16px' }}>
              <Card
                title={t('template.basicInfo')}
                variant="borderless"
                styles={{
                  body: {
                    padding: '8px 16px'
                  },
                  header: {
                    padding: '0 16px 4px'
                  }
                }}
              >
                <Row gutter={12} align="middle">
                  <Col span={6}>
                    <Form.Item
                      name="name"
                      label={t('common.name')}
                      rules={[{ required: true }]}
                      style={{ marginBottom: 0 }}
                    >
                      <Input />
                    </Form.Item>
                  </Col>
                  <Col span={6}>
                    <Form.Item
                      name="agent_type"
                      label={t('template.agentType')}
                      rules={[{ required: true, message: t('template.pleaseSelectAgentType') }]}
                      style={{ marginBottom: 0 }}
                    >
                      <Select
                        value={agentTemplateStore.agentType}
                        placeholder={t('template.selectAgentType')}
                        style={{ width: '100%' }}
                        allowClear
                        onChange={async (value) => {
                          await agentTemplateStore.setAgentType(value);
                        }}
                        options={agentTypeOptions}
                      />
                    </Form.Item>
                  </Col>
                  <Col span={6}>
                    <Form.Item
                      name="agent_class"
                      label={t('template.agentClass')}
                      rules={[{ required: true, message: t('template.pleaseSelectAgentClass') }]}
                      style={{ marginBottom: 0 }}
                    >
                      <Select
                        value={agentTemplateStore.agentClass}
                        placeholder={agentTemplateStore.agentType ? t('template.selectAgentClass') : t('template.selectAgentTypeFirst')}
                        style={{ width: '100%' }}
                        allowClear
                        disabled={!agentTemplateStore.agentType || agentTemplateStore.loadingAgentClasses}
                        loading={agentTemplateStore.loadingAgentClasses}
                        onChange={async (value) => {
                          await agentTemplateStore.setAgentClass(value);
                        }}
                        options={agentTemplateStore.agentClasses}
                      />
                    </Form.Item>
                  </Col>
                  <Col span={6}>
                    <Form.Item
                      name="description"
                      label={t('common.description')}
                      style={{ marginBottom: 0 }}
                    >
                      <Input placeholder={t('template.descriptionPlaceholder')} />
                    </Form.Item>
                  </Col>
                </Row>
              </Card>
            </Col>

            <Col span={18} style={{ borderRight: '1px solid #f0f0f0' }}>
              <div style={{
                height: 'calc(100vh - 200px)',
                overflowY: 'auto',
                padding: '0 16px',
                position: 'sticky',
                top: 0
              }}>
                <AgentConfiguration />
                <BlockConfiguration 
                  onBlockContextChange={agentTemplateStore.setBlockContexts}
                  selectedBlocks={selectedBlocks}
                  onSelectedBlocksChange={setSelectedBlocks}
                />
              </div>
            </Col>

            <Col span={6}>
              <div style={{
                height: 'calc(100vh - 200px)',
                overflowY: 'auto',
                padding: '0 16px',
                position: 'sticky',
                top: 0
              }}>
                <AgentInfoSidebar blockContexts={agentTemplateStore.blockContexts} />
              </div>
            </Col>
          </Row>
        </Form>
      </Card>
    </div>
  );
});

export default AgentTemplateForm; 