import React, { useState, useEffect, useCallback } from 'react';
import { Table, Button, Card, Space, Modal, message, Tooltip, Input, Popconfirm, Form, Col, Row, InputNumber, Select, Divider, Typography, Descriptions } from 'antd';
import { PlusOutlined, EyeOutlined, DeleteOutlined, ExportOutlined, MinusCircleOutlined } from '@ant-design/icons';
import { AgentsConfig, ConfigWrapper, AgentConfig } from '../../types/config';
import { fetchCustom } from '../../components/fetch';
import dayjs from 'dayjs';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router';
import { ApiAgentTemplate } from '../../types/agentTemplate';
import { ApiAgentProfile } from '../../types/profile';

const { Option } = Select;
const { Text } = Typography;

interface FormValues {
    name: string;
    description?: string;
    citizens: Array<{
        templateId?: string;
        number?: number;
        memory_from_file?: string;
    }>;
    supervisor?: {
        templateId?: string;
        memory_from_file?: string;
    };
    firmNumber: number;
    governmentNumber: number;
    bankNumber: number;
    nbsNumber: number;
}

const AgentList: React.FC = () => {
    const navigate = useNavigate();
    const { t } = useTranslation();
    const [agents, setAgents] = useState<ConfigWrapper<AgentsConfig>[]>([]);
    const [loading, setLoading] = useState(false);
    const [searchText, setSearchText] = useState('');
    const [isModalVisible, setIsModalVisible] = useState(false);
    const [isPreviewVisible, setIsPreviewVisible] = useState(false);
    const [, setCurrentAgent] = useState<ConfigWrapper<AgentsConfig> | null>(null);
    const [previewAgent, setPreviewAgent] = useState<ConfigWrapper<AgentsConfig> | null>(null);
    const [templates, setTemplates] = useState<ApiAgentTemplate[]>([]);
    const [profiles, setProfiles] = useState<ApiAgentProfile[]>([]);
    const [form] = Form.useForm<FormValues>();

    // Load templates
    useEffect(() => {
        const loadTemplates = async () => {
            try {
                const response = await fetchCustom('/api/agent-templates');
                if (response.ok) {
                    const data = await response.json();
                    setTemplates(data.data);
                } else {
                    message.error('Failed to load templates');
                }
            } catch (_error) {
                message.error('Error loading templates');
            }
        };
        loadTemplates();
    }, []);

    // Load profiles
    useEffect(() => {
        const loadProfiles = async () => {
            try {
                const response = await fetchCustom('/api/agent-profiles');
                if (response.ok) {
                    const data = await response.json();
                    setProfiles(data.data || []);
                } else {
                    message.error('Failed to load profiles');
                }
            } catch (_error) {
                message.error('Error loading profiles');
            }
        };
        loadProfiles();
    }, []);

    // Load agent configurations
    const loadAgents = useCallback(async () => {
        setLoading(true);
        try {
            const res = await fetchCustom('/api/agent-configs');
            if (!res.ok) {
                throw new Error(await res.text());
            }
            const data = (await res.json()).data as ConfigWrapper<AgentsConfig>[];
            setAgents(data);
        } catch (error) {
            message.error(t('agent.messages.loadFailed') + `: ${JSON.stringify(error.message)}`, 3);
            console.error(error);
        } finally {
            setLoading(false);
        }
    }, [t]);
    // Initialize data
    useEffect(() => {
        const init = async () => {
            await loadAgents();
        };
        init();
    }, [loadAgents]);

    // Handle search
    const handleSearch = (e: React.ChangeEvent<HTMLInputElement>) => {
        setSearchText(e.target.value);
    };

    // Filter agents based on search text
    const filteredAgents = agents.filter(agent =>
        agent.name.toLowerCase().includes(searchText.toLowerCase()) ||
        (agent.description && agent.description.toLowerCase().includes(searchText.toLowerCase()))
    );

    // Handle create new agent
    const handleCreate = () => {
        setCurrentAgent(null);
        form.setFieldsValue({
            name: `Agent ${agents.length + 1}`,
            description: '',
            citizens: [{}],
            supervisor: undefined,
            firmNumber: 1,
            governmentNumber: 1,
            bankNumber: 1,
            nbsNumber: 1,
        });
        setIsModalVisible(true);
    };

    // Handle preview agent
    const handlePreview = (agent: ConfigWrapper<AgentsConfig>) => {
        setPreviewAgent(agent);
        setIsPreviewVisible(true);
    };

    // Handle delete agent
    const handleDelete = async (id: string) => {
        try {
            const res = await fetchCustom(`/api/agent-configs/${id}`, {
                method: 'DELETE'
            });
            if (!res.ok) {
                throw new Error(await res.text());
            }
            message.success(t('agent.messages.deleteSuccess'));
            loadAgents();
        } catch (error) {
            message.error(t('agent.messages.deleteFailed') + `: ${JSON.stringify(error.message)}`, 3);
            console.error(error);
        }
    };

    // Handle export agent
    const handleExport = (agent: ConfigWrapper<AgentsConfig>) => {
        const dataStr = JSON.stringify(agent, null, 2);
        const dataUri = `data:application/json;charset=utf-8,${encodeURIComponent(dataStr)}`;

        const exportFileDefaultName = `${agent.name.replace(/\s+/g, '_')}_agent.json`;

        const linkElement = document.createElement('a');
        linkElement.setAttribute('href', dataUri);
        linkElement.setAttribute('download', exportFileDefaultName);
        linkElement.click();
    };

    // Convert form values to agent config
    const convertFormToConfig = async (formValues: FormValues): Promise<AgentsConfig> => {
        const config: AgentsConfig = {
            citizens: [],
            firms: [{ number: formValues.firmNumber, agent_class: 'firm' }],
            governments: [{ number: formValues.governmentNumber, agent_class: 'government' }],
            banks: [{ number: formValues.bankNumber, agent_class: 'bank' }],
            nbs: [{ number: formValues.nbsNumber, agent_class: 'nbs' }],
        };

        // Process citizens
        const citizenPromises = formValues.citizens.map(async (citizen) => {
            if (citizen.templateId) {
                try {
                    const response = await fetchCustom(`/api/agent-templates/${citizen.templateId}`);
                    if (response.ok) {
                        const template = (await response.json()).data;

                        const result: AgentConfig = {
                            agent_class: template.agent_class || 'citizen',
                            agent_params: template.agent_params,
                            blocks: template.blocks
                        };

                        // 如果设置了number，则添加number字段
                        if (citizen.number) {
                            result.number = citizen.number;
                        }

                        // 如果设置了memory_from_file，则添加memory_from_file字段
                        if (citizen.memory_from_file) {
                            result.memory_from_file = citizen.memory_from_file;
                        }

                        // 如果既没有number也没有memory_from_file，设置默认number为1
                        if (!citizen.number && !citizen.memory_from_file) {
                            result.number = 1;
                        }

                        return result;
                    }
                } catch (error) {
                    console.error('Error fetching template:', error);
                }
            }

            // Fallback if no template
            const result: AgentConfig = {
                agent_class: 'citizen',
            };

            // 如果设置了number，则添加number字段
            if (citizen.number) {
                result.number = citizen.number;
            }

            // 如果设置了memory_from_file，则添加memory_from_file字段
            if (citizen.memory_from_file) {
                result.memory_from_file = citizen.memory_from_file;
            }

            // 如果既没有number也没有memory_from_file，设置默认number为1
            if (!citizen.number && !citizen.memory_from_file) {
                result.number = 1;
            }

            return result;
        });

        config.citizens = await Promise.all(citizenPromises);

        // Process supervisor
        if (formValues.supervisor?.templateId) {
            try {
                const response = await fetchCustom(`/api/agent-templates/${formValues.supervisor.templateId}`);
                if (response.ok) {
                    const template = (await response.json()).data;
                    const convertedBlocks: AgentConfig['blocks'] = {};
                    Object.entries(template.blocks).forEach(([key, value]) => {
                        const blockKey = key.toLowerCase();
                        convertedBlocks[blockKey] = value;
                    });

                    config.supervisor = {
                        agent_class: template.agent_class || 'supervisor',
                        memory_from_file: formValues.supervisor.memory_from_file,
                        agent_params: template.agent_params,
                        blocks: convertedBlocks
                    };
                }
            } catch (error) {
                console.error('Error fetching supervisor template:', error);
            }
        }

        return config;
    };

    // Handle modal OK
    const handleModalOk = async () => {
        try {
            const formValues = await form.validateFields();
            const config = await convertFormToConfig(formValues);

            const requestBody = {
                name: formValues.name,
                description: formValues.description || '',
                config,
            };

            const res = await fetchCustom('/api/agent-configs', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(requestBody),
            });

            if (!res.ok) {
                throw new Error(await res.text());
            }

            message.success(t('agent.messages.createSuccess'));
            setIsModalVisible(false);
            loadAgents();
        } catch (error) {
            message.error(t('agent.messages.createFailed') + `: ${JSON.stringify(error.message)}`, 3);
            console.error('Validation failed:', error);
        }
    };

    // Handle modal cancel
    const handleModalCancel = () => {
        setIsModalVisible(false);
        form.resetFields();
    };

    // Handle preview modal cancel
    const handlePreviewCancel = () => {
        setIsPreviewVisible(false);
        setPreviewAgent(null);
    };

    // Render agent details for preview
    const renderAgentDetails = (agent: AgentConfig, title: string) => {
        const items: { key: string; label: string; children: React.ReactNode }[] = [
            {
                key: 'agent_class',
                label: t('agent.agentClass'),
                children: agent.agent_class,
            },
            {
                key: 'number',
                label: t('agent.number'),
                children: agent.number,
            },
        ];

        if (agent.memory_from_file) {
            // 解析 memory_from_file 路径，格式: agent_profiles/<tenant_id>/<id>.json
            const pathParts = agent.memory_from_file.split('/');
            let profileDisplay: React.ReactNode = agent.memory_from_file;

            if (pathParts.length >= 3 && pathParts[0] === 'agent_profiles') {
                // 在 profiles 中查找匹配的 profile
                const matchedProfile = profiles.find(profile =>
                    profile.file_path === agent.memory_from_file
                );

                if (matchedProfile) {
                    profileDisplay = (
                        <Tooltip title={matchedProfile.description}>
                            {matchedProfile.name} ({matchedProfile.record_count} {t('agent.records')})
                        </Tooltip>
                    );
                }
            }

            items.push({
                key: 'memory_from_file',
                label: `${t('agent.memoryFromFile')}`,
                children: profileDisplay,
            });
        }

        if (agent.agent_params) {
            items.push({
                key: 'agent_params',
                label: t('agent.agentParams'),
                children: <pre style={{
                    background: '#f5f5f5',
                    padding: '8px',
                    borderRadius: '4px',
                    fontSize: '12px',
                    maxHeight: '200px',
                    overflow: 'auto',
                    marginTop: '4px',
                    wordWrap: 'break-word',
                    whiteSpace: 'pre-wrap'
                }}>
                    {JSON.stringify(agent.agent_params, null, 2)}
                </pre>
            });
        }

        if (agent.blocks) {
            items.push({
                key: 'blocks',
                label: t('agent.blocks'),
                children: <pre style={{
                    background: '#f5f5f5',
                    padding: '8px',
                    borderRadius: '4px',
                    fontSize: '12px',
                    maxHeight: '200px',
                    overflow: 'auto',
                    marginTop: '4px',
                    wordWrap: 'break-word',
                    whiteSpace: 'pre-wrap'
                }}>
                    {JSON.stringify(agent.blocks, null, 2)}
                </pre>,
            });
        }

        return (
            <div style={{ marginBottom: '16px' }}>
                <Text strong>{title}</Text>
                <Descriptions
                    bordered
                    size="small"
                    column={1}
                    items={items}
                />
            </div>
        );
    };

    // Table columns
    const columns = [
        {
            title: t('common.name'),
            dataIndex: 'name',
            key: 'name',
            sorter: (a: ConfigWrapper<AgentsConfig>, b: ConfigWrapper<AgentsConfig>) => a.name.localeCompare(b.name)
        },
        {
            title: t('common.description'),
            dataIndex: 'description',
            key: 'description',
            ellipsis: true
        },
        {
            title: t('common.lastUpdated'),
            dataIndex: 'updated_at',
            key: 'updated_at',
            render: (text: string) => dayjs(text).format('YYYY-MM-DD HH:mm:ss'),
            sorter: (a: ConfigWrapper<AgentsConfig>, b: ConfigWrapper<AgentsConfig>) => dayjs(a.updated_at).valueOf() - dayjs(b.updated_at).valueOf()
        },
        {
            title: t('common.actions'),
            key: 'actions',
            render: (_: unknown, record: ConfigWrapper<AgentsConfig>) => (
                <Space size="small">
                    <Tooltip title={t('common.preview')}>
                        <Button icon={<EyeOutlined />} size="small" onClick={() => handlePreview(record)} />
                    </Tooltip>
                    <Tooltip title={t('common.export')}>
                        <Button icon={<ExportOutlined />} size="small" onClick={() => handleExport(record)} />
                    </Tooltip>
                    {
                        (record.tenant_id ?? '') !== '' && (
                            <Tooltip title={t('common.delete')}>
                                <Popconfirm
                                    title={t('common.deleteConfirm')}
                                    onConfirm={() => handleDelete(record.id)}
                                    okText={t('common.submit')}
                                    cancelText={t('common.cancel')}
                                >
                                    <Button icon={<DeleteOutlined />} size="small" danger />
                                </Popconfirm>
                            </Tooltip>
                        )
                    }
                </Space>
            )
        }
    ];

    return (
        <Card
            title={t('agent.title')}
            extra={
                <Space>
                    <Button onClick={() => navigate('/agent-templates')}>{t('agent.templates')}</Button>
                    <Button onClick={() => navigate('/profiles')}>{t('agent.profiles')}</Button>
                    <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>{t('agent.createNew')}</Button>
                </Space>
            }
        >
            <Input.Search
                placeholder={t('agent.searchPlaceholder')}
                onChange={handleSearch}
                style={{ marginBottom: 8 }}
            />

            <Table
                columns={columns}
                dataSource={filteredAgents}
                rowKey="id"
                loading={loading}
                pagination={{ pageSize: 10, size: 'small', showSizeChanger: false }}
            />

            {/* 创建/编辑 Modal */}
            <Modal
                title={t('agent.createTitle')}
                open={isModalVisible}
                onOk={handleModalOk}
                onCancel={handleModalCancel}
                width="75vw"
                destroyOnHidden
            >
                <Form
                    form={form}
                    layout="vertical"
                >
                    {/* 元数据部分 */}
                    <Card
                        title={t('common.metadataTitle')}
                        style={{ marginBottom: 8 }}
                    >
                        <Row gutter={8}>
                            <Col span={8}>
                                <Form.Item
                                    name="name"
                                    label={t('common.name')}
                                    rules={[{ required: true, message: t('common.nameRequired') }]}
                                    style={{ marginBottom: 8 }}
                                >
                                    <Input placeholder={t('common.namePlaceholder')} />
                                </Form.Item>
                            </Col>
                            <Col span={16}>
                                <Form.Item
                                    name="description"
                                    label={t('common.description')}
                                    style={{ marginBottom: 8 }}
                                >
                                    <Input.TextArea
                                        rows={1}
                                        placeholder={t('common.descriptionPlaceholder')}
                                    />
                                </Form.Item>
                            </Col>
                        </Row>
                    </Card>

                    {/* Agent配置部分 */}
                    <Card
                        title={t('agent.settingsTitle')}
                    >
                        {/* 市民组配置 */}
                        <div style={{ marginBottom: 8 }}>
                            <Text strong>{t('agent.citizenGroup')}</Text>
                        </div>
                        <Form.List name="citizens" initialValue={[{}]}>
                            {(fields, { add, remove }) => (
                                <>
                                    {fields.map(({ key, name, ...restField }) => (
                                        <Row key={key} gutter={8} align="middle" style={{ marginBottom: 8 }}>
                                            <Col span={8}>
                                                <Form.Item
                                                    {...restField}
                                                    name={[name, 'templateId']}
                                                    label={t('agent.selectTemplate')}
                                                    rules={[{ required: true, message: t('agent.pleaseSelectTemplate') }]}
                                                    style={{ marginBottom: 8 }}
                                                >
                                                    <Select
                                                        loading={loading}
                                                        placeholder={t('agent.selectTemplatePlaceholder')}
                                                        style={{ width: '100%' }}
                                                    >
                                                        {templates
                                                            .filter(template => template.agent_type === 'citizen')
                                                            .map(template => (
                                                                <Option key={template.id} value={template.id}>
                                                                    {template.name}
                                                                    <span style={{ color: '#999', marginLeft: 8 }}>
                                                                        {template.description}
                                                                    </span>
                                                                </Option>
                                                            ))}
                                                    </Select>
                                                </Form.Item>
                                            </Col>
                                            <Col span={4}>
                                                <Form.Item
                                                    {...restField}
                                                    name={[name, 'number']}
                                                    label={t('agent.numberLabel')}
                                                    style={{ marginBottom: 8 }}
                                                >
                                                    <InputNumber min={1} style={{ width: '100%' }} />
                                                </Form.Item>
                                            </Col>
                                            <Col span={8}>
                                                <Form.Item
                                                    {...restField}
                                                    name={[name, 'memory_from_file']}
                                                    label={t('agent.selectProfile')}
                                                    style={{ marginBottom: 8 }}
                                                >
                                                    <Select
                                                        placeholder={t('agent.selectProfilePlaceholder')}
                                                        loading={loading}
                                                        allowClear
                                                    >
                                                        {profiles.map(profile => (
                                                            <Option key={profile.id} value={profile.file_path}>
                                                                {profile.name}
                                                                <span style={{ color: '#999', marginLeft: 8 }}>
                                                                    ({profile.record_count} {t('agent.records')})
                                                                </span>
                                                            </Option>
                                                        ))}
                                                    </Select>
                                                </Form.Item>
                                            </Col>
                                            <Col span={4}>
                                                <Button
                                                    type="text"
                                                    danger
                                                    icon={<MinusCircleOutlined />}
                                                    onClick={() => remove(name)}
                                                    style={{ marginTop: 24 }}
                                                />
                                            </Col>
                                        </Row>
                                    ))}
                                    <Button
                                        type="dashed"
                                        onClick={() => add({})}
                                        block
                                        icon={<PlusOutlined />}
                                        style={{ marginBottom: 16 }}
                                    >
                                        {t('agent.addGroup')}
                                    </Button>
                                </>
                            )}
                        </Form.List>

                        <Divider />

                        {/* 机构配置 */}
                        <div style={{ marginBottom: 8 }}>
                            <Text strong>{t('agent.institutions')}</Text>
                        </div>
                        <Row gutter={16}>
                            <Col span={6}>
                                <Form.Item
                                    name="firmNumber"
                                    label={t('agent.firmGroup')}
                                    initialValue={1}
                                    rules={[{ required: true, message: t('agent.pleaseInputFirmNumber') }]}
                                    style={{ marginBottom: 8 }}
                                >
                                    <InputNumber min={0} style={{ width: '100%' }} />
                                </Form.Item>
                            </Col>
                            <Col span={6}>
                                <Form.Item
                                    name="governmentNumber"
                                    label={t('agent.governmentGroup')}
                                    initialValue={1}
                                    rules={[{ required: true, message: t('agent.pleaseInputGovernmentNumber') }]}
                                    style={{ marginBottom: 8 }}
                                >
                                    <InputNumber min={0} style={{ width: '100%' }} />
                                </Form.Item>
                            </Col>
                            <Col span={6}>
                                <Form.Item
                                    name="bankNumber"
                                    label={t('agent.bankGroup')}
                                    initialValue={1}
                                    rules={[{ required: true, message: t('agent.pleaseInputBankNumber') }]}
                                    style={{ marginBottom: 8 }}
                                >
                                    <InputNumber min={0} style={{ width: '100%' }} />
                                </Form.Item>
                            </Col>
                            <Col span={6}>
                                <Form.Item
                                    name="nbsNumber"
                                    label={t('agent.nbsGroup')}
                                    initialValue={1}
                                    rules={[{ required: true, message: t('agent.pleaseInputNbsNumber') }]}
                                    style={{ marginBottom: 8 }}
                                >
                                    <InputNumber min={0} style={{ width: '100%' }} />
                                </Form.Item>
                            </Col>
                        </Row>

                        <Divider />

                        {/* 监督者配置 */}
                        <div style={{ marginBottom: 8 }}>
                            <Text strong>{t('agent.supervisor')}</Text>
                        </div>
                        <Row gutter={16}>
                            <Col span={12}>
                                <Form.Item
                                    name={['supervisor', 'templateId']}
                                    label={t('agent.selectTemplate')}
                                    style={{ marginBottom: 8 }}
                                >
                                    <Select
                                        loading={loading}
                                        placeholder={t('agent.selectSupervisorTemplate')}
                                        style={{ width: '100%' }}
                                        allowClear
                                    >
                                        {templates
                                            .filter(template => template.agent_type === 'supervisor')
                                            .map(template => (
                                                <Option key={template.id} value={template.id}>
                                                    {template.name}
                                                    <span style={{ color: '#999', marginLeft: 8 }}>
                                                        {template.description}
                                                    </span>
                                                </Option>
                                            ))}
                                    </Select>
                                </Form.Item>
                            </Col>
                            <Col span={12}>
                                <Form.Item
                                    name={['supervisor', 'memory_from_file']}
                                    label={t('agent.selectProfile')}
                                    style={{ marginBottom: 8 }}
                                    rules={[
                                        ({ getFieldValue }) => ({
                                            validator(_, value) {
                                                const templateId = getFieldValue(['supervisor', 'templateId']);
                                                if (templateId && !value) {
                                                    return Promise.reject(new Error(t('agent.messages.supervisorProfileRequired')));
                                                }
                                                return Promise.resolve();
                                            },
                                        }),
                                    ]}
                                    dependencies={[['supervisor', 'templateId']]}
                                >
                                    <Select
                                        placeholder={t('agent.selectProfilePlaceholder')}
                                        loading={loading}
                                        allowClear
                                    >
                                        {profiles.map(profile => (
                                            <Option key={profile.id} value={profile.file_path}>
                                                {profile.name}
                                                <span style={{ color: '#999', marginLeft: 8 }}>
                                                    ({profile.record_count} {t('agent.records')})
                                                </span>
                                            </Option>
                                        ))}
                                    </Select>
                                </Form.Item>
                            </Col>
                        </Row>
                    </Card>
                </Form>
            </Modal>

            {/* 预览 Modal */}
            <Modal
                title={t('common.preview')}
                open={isPreviewVisible}
                onCancel={handlePreviewCancel}
                footer={[
                    <Button key="close" onClick={handlePreviewCancel}>
                        {t('common.close')}
                    </Button>
                ]}
                width="80vw"
            >
                {previewAgent && (
                    <div>
                        {/* 基本信息 */}
                        <Descriptions
                            title={t('common.basicInfo')}
                            bordered
                            size="small"
                            column={2}
                            style={{ marginBottom: '16px' }}
                            items={[
                                {
                                    key: 'name',
                                    label: t('common.name'),
                                    children: previewAgent.name,
                                },
                                {
                                    key: 'description',
                                    label: t('common.description'),
                                    children: previewAgent.description || '-',
                                },
                                {
                                    key: 'created_at',
                                    label: t('common.createdAt'),
                                    children: previewAgent.created_at ? dayjs(previewAgent.created_at).format('YYYY-MM-DD HH:mm:ss') : '-',
                                },
                                {
                                    key: 'updated_at',
                                    label: t('common.lastUpdated'),
                                    children: previewAgent.updated_at ? dayjs(previewAgent.updated_at).format('YYYY-MM-DD HH:mm:ss') : '-',
                                },
                            ]}
                        />

                        {/* 市民详情 */}
                        {previewAgent.config.citizens && previewAgent.config.citizens.length > 0 && (
                            <div style={{ marginBottom: '16px' }}>
                                <Text strong>{t('agent.citizenGroup')}</Text>
                                {previewAgent.config.citizens.map((citizen, index) =>
                                    renderAgentDetails(citizen, `${t('agent.citizenGroup')} ${index + 1}`)
                                )}
                            </div>
                        )}

                        <Divider />

                        {/* 机构数量 */}
                        <Descriptions
                            title={t('agent.institutions')}
                            bordered
                            size="small"
                            column={4}
                            style={{ marginBottom: '16px' }}
                            items={[
                                {
                                    key: 'firms',
                                    label: t('agent.firmGroup'),
                                    children: previewAgent.config.firms?.[0]?.number || 0,
                                },
                                {
                                    key: 'governments',
                                    label: t('agent.governmentGroup'),
                                    children: previewAgent.config.governments?.[0]?.number || 0,
                                },
                                {
                                    key: 'banks',
                                    label: t('agent.bankGroup'),
                                    children: previewAgent.config.banks?.[0]?.number || 0,
                                },
                                {
                                    key: 'nbs',
                                    label: t('agent.nbsGroup'),
                                    children: previewAgent.config.nbs?.[0]?.number || 0,
                                },
                            ]}
                        />

                        <Divider />

                        {/* 监督者详情 */}
                        {previewAgent.config.supervisor && (
                            renderAgentDetails(previewAgent.config.supervisor, t('agent.supervisor'))
                        )}
                    </div>
                )}
            </Modal>
        </Card>
    );
};

export default AgentList; 