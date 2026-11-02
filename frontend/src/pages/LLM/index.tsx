import React, { useState, useEffect, useCallback } from 'react';
import { Table, Button, Card, Space, Modal, message, Tooltip, Input, Popconfirm, Form, Col, Row, Select } from 'antd';
import { PlusOutlined, EditOutlined, DeleteOutlined, CopyOutlined, ExportOutlined, MinusCircleOutlined } from '@ant-design/icons';
import { ConfigWrapper, LLMConfig } from '../../types/config';
import { fetchCustom } from '../../components/fetch';
import dayjs from 'dayjs';
import { useTranslation } from 'react-i18next';
import { LLMProviderType } from '../../utils/enums';

// Define provider model options
const providerModels = {
    deepseek: [
        { value: 'deepseek-reasoner', label: 'DeepSeek-R1' },
        { value: 'deepseek-chat', label: 'DeepSeek-V3' },
    ],
    openai: [
        { value: 'gpt-4.5', label: 'GPT-4.5 Preview' },
        { value: 'gpt-4o', label: 'GPT-4o' },
        { value: 'gpt-4o-mini', label: 'GPT-4o mini' },
        { value: 'gpt-4-turbo', label: 'GPT-4 Turbo' },
        { value: 'gpt-4', label: 'GPT-4' },
        { value: 'gpt-3.5-turbo', label: 'GPT-3.5 Turbo' },
    ],
    qwen: [
        { value: 'qwen-max', label: 'Qwen Max' },
        { value: 'qwen-plus', label: 'Qwen Plus' },
        { value: 'qwen-turbo', label: 'Qwen Turbo' },
        { value: 'qwen2.5-72b-instruct', label: 'qwen2.5-72b-instruct' },
        { value: 'qwen2.5-32b-instruct', label: 'qwen2.5-32b-instruct' },
        { value: 'qwen2.5-14b-instruct-1m', label: 'qwen2.5-14b-instruct-1m' },
        { value: 'qwen2.5-14b-instruct', label: 'qwen2.5-14b-instruct' },
        { value: 'qwen2.5-7b-instruct-1m', label: 'qwen2.5-7b-instruct-1m' },
        { value: 'qwen2.5-7b-instruct', label: 'qwen2.5-7b-instruct' },
        { value: 'qwen2-72b-instruct', label: 'qwen2-72b-instruct' },
        { value: 'qwen2-57b-a14b-instruct', label: 'qwen2-57b-a14b-instruct' },
        { value: 'qwen2-7b-instruct', label: 'qwen2-7b-instruct' },
    ],
    siliconflow: [
        { value: 'Pro/deepseek-ai/DeepSeek-V3', label: 'Pro/deepseek-ai/DeepSeek-V3' },
        { value: 'deepseek-ai/DeepSeek-V3', label: 'deepseek-ai/DeepSeek-V3' },
        { value: 'deepseek-ai/DeepSeek-R1-Distill-Qwen-32B', label: 'deepseek-ai/DeepSeek-R1-Distill-Qwen-32B' },
        { value: 'deepseek-ai/DeepSeek-R1-Distill-Qwen-14B', label: 'deepseek-ai/DeepSeek-R1-Distill-Qwen-14B' },
        { value: 'Qwen/QwQ-32B', label: 'Qwen/QwQ-32B' },
        { value: 'Qwen/QVQ-72B-Preview', label: 'Qwen/QVQ-72B-Preview' },
    ],
    zhipuai: [
        { value: 'glm-4-air', label: 'GLM-4-Air' },
        { value: 'glm-4-flash', label: 'GLM-4-Flash' },
        { value: 'glm-4-plus', label: 'GLM-4-Plus' },
    ],
};

const LLM: React.FC = () => {
    const { t } = useTranslation();
    const [llms, setLLMs] = useState<ConfigWrapper<LLMConfig[]>[]>([]);
    const [loading, setLoading] = useState(false);
    const [searchText, setSearchText] = useState('');
    const [isModalVisible, setIsModalVisible] = useState(false);
    const [currentLLM, setCurrentLLM] = useState<ConfigWrapper<LLMConfig[]> | null>(null);
    const [selectedProviders, setSelectedProviders] = useState<Record<number, LLMProviderType>>({});
    const [form] = Form.useForm();

    // Load LLM configurations
    const loadLLMs = useCallback(async () => {
        setLoading(true);
        try {
            const res = await fetchCustom('/api/llm-configs');
            if (!res.ok) {
                throw new Error(await res.text());
            }
            const data = (await res.json()).data as ConfigWrapper<LLMConfig[]>[];
            setLLMs(data);
        } catch (error) {
            message.error(t('llm.loadError', { error: JSON.stringify(error.message) }), 3);
            console.error(error);
        } finally {
            setLoading(false);
        }
    }, [t]);
    // Initialize data
    useEffect(() => {
        const init = async () => {
            await loadLLMs();
        };
        init();
    }, [loadLLMs]);

    // Handle search
    const handleSearch = (e: React.ChangeEvent<HTMLInputElement>) => {
        setSearchText(e.target.value);
    };

    // Filter LLMs based on search text
    const filteredLLMs = llms.filter(llm =>
        llm.name.toLowerCase().includes(searchText.toLowerCase()) ||
        (llm.description && llm.description.toLowerCase().includes(searchText.toLowerCase()))
    );

    // Handle create new LLM
    const handleCreate = () => {
        setCurrentLLM(null);
        form.setFieldsValue({
            name: `LLM ${llms.length + 1}`,
            description: '',
            llm_configs: []
        });
        setSelectedProviders({});
        setIsModalVisible(true);
    };

    // Handle edit LLM
    const handleEdit = (llm: ConfigWrapper<LLMConfig[]>) => {
        setCurrentLLM(llm);
        form.setFieldsValue({
            name: llm.name,
            description: llm.description,
            llm_configs: llm.config
        });

        // Initialize selected providers
        const initialProviders: Record<number, LLMProviderType> = {};
        llm.config.forEach((config, index) => {
            if (config.provider) {
                initialProviders[index] = config.provider;
            }
        });
        setSelectedProviders(initialProviders);
        setIsModalVisible(true);
    };

    // Handle duplicate LLM
    const handleDuplicate = (llm: ConfigWrapper<LLMConfig[]>) => {
        setCurrentLLM(null);
        form.setFieldsValue({
            name: `${llm.name} (Copy)`,
            description: llm.description,
            llm_configs: llm.config
        });

        // Initialize selected providers
        const initialProviders: Record<number, LLMProviderType> = {};
        llm.config.forEach((config, index) => {
            if (config.provider) {
                initialProviders[index] = config.provider;
            }
        });
        setSelectedProviders(initialProviders);
        setIsModalVisible(true);
    };

    // Handle delete LLM
    const handleDelete = async (id: string) => {
        try {
            const res = await fetchCustom(`/api/llm-configs/${id}`, {
                method: 'DELETE'
            });
            if (!res.ok) {
                throw new Error(await res.text());
            }
            message.success(t('llm.deleteSuccess'));
            loadLLMs();
        } catch (error) {
            message.error(t('llm.deleteError', { error: JSON.stringify(error.message) }), 3);
            console.error(error);
        }
    };

    // Handle export LLM
    const handleExport = (llm: ConfigWrapper<LLMConfig[]>) => {
        const dataStr = JSON.stringify(llm, null, 2);
        const dataUri = `data:application/json;charset=utf-8,${encodeURIComponent(dataStr)}`;

        const exportFileDefaultName = `${llm.name.replace(/\s+/g, '_')}_llm.json`;

        const linkElement = document.createElement('a');
        linkElement.setAttribute('href', dataUri);
        linkElement.setAttribute('download', exportFileDefaultName);
        linkElement.click();
    };

    // Handle modal OK
    const handleModalOk = async () => {
        try {
            const values = await form.validateFields();
            const configData = {
                name: values.name,
                description: values.description || '',
                config: values.llm_configs,
            };

            let res: Response;
            if (currentLLM) {
                res = await fetchCustom(`/api/llm-configs/${currentLLM.id}`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(configData),
                });
            } else {
                res = await fetchCustom('/api/llm-configs', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(configData),
                });
            }
            if (!res.ok) {
                throw new Error(await res.text());
            }

            message.success(t(currentLLM ? 'llm.updateSuccess' : 'llm.createSuccess'));
            setIsModalVisible(false);
            loadLLMs();
        } catch (error) {
            message.error(t(currentLLM ? 'llm.updateError' : 'llm.createError', { error: JSON.stringify(error.message) }), 3);
            console.error('Validation failed:', error);
        }
    };

    // Handle modal cancel
    const handleModalCancel = () => {
        setIsModalVisible(false);
    };

    // Table columns
    const columns = [
        {
            title: t('common.name'),
            dataIndex: 'name',
            key: 'name',
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
            render: (text: string) => dayjs(text).format('YYYY-MM-DD HH:mm:ss')
        },
        {
            title: t('common.actions'),
            key: 'action',
            render: (_: unknown, record: ConfigWrapper<LLMConfig[]>) => (
                <Space size="small">
                    {
                        (record.tenant_id ?? '') !== '' && (
                            <Tooltip title={t('common.edit')}>
                                <Button icon={<EditOutlined />} size="small" onClick={() => handleEdit(record)} />
                            </Tooltip>
                        )
                    }
                    <Tooltip title={t('common.duplicate')}>
                        <Button icon={<CopyOutlined />} size="small" onClick={() => handleDuplicate(record)} />
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
            title={t('llm.title')}
            extra={<Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>{t('llm.createNew')}</Button>}
        >
            <Input.Search
                placeholder={t('llm.searchPlaceholder')}
                onChange={handleSearch}
                style={{ marginBottom: 16 }}
            />

            <Table
                columns={columns}
                dataSource={filteredLLMs}
                rowKey="id"
                loading={loading}
                pagination={{ pageSize: 10 }}
            />

            <Modal
                title={currentLLM ? t('llm.editTitle') : t('llm.createTitle')}
                open={isModalVisible}
                onOk={handleModalOk}
                onCancel={handleModalCancel}
                width="80vw"
                destroyOnHidden
            >
                <Form
                    form={form}
                    layout="vertical"
                >
                    <Card title={t('llm.metadataTitle')} style={{ marginBottom: 8 }}>
                        <Row gutter={16}>
                            <Col span={8}>
                                <Form.Item
                                    name="name"
                                    label={t('common.name')}
                                    rules={[{ required: true, message: t('common.nameRequired') }]}
                                >
                                    <Input placeholder={t('common.namePlaceholder')} />
                                </Form.Item>
                            </Col>
                            <Col span={16}>
                                <Form.Item
                                    name="description"
                                    label={t('common.description')}
                                >
                                    <Input.TextArea
                                        rows={1}
                                        placeholder={t('common.descriptionPlaceholder')}
                                    />
                                </Form.Item>
                            </Col>
                        </Row>
                    </Card>

                    <Card title={t('llm.settingsTitle')}>
                        <Form.List name="llm_configs">
                            {(fields, { add, remove }) => (
                                <>
                                    {fields.map(({ key, name, ...restField }) => (
                                        <Card
                                            key={key}
                                            title={`${t('llm.providerTitle')} ${name + 1}`}
                                            style={{ marginBottom: 8 }}
                                            extra={
                                                fields.length > 1 ? (
                                                    <MinusCircleOutlined onClick={() => remove(name)} />
                                                ) : null
                                            }
                                        >
                                            <Row gutter={16}>
                                                <Col span={8}>
                                                    <Form.Item
                                                        {...restField}
                                                        name={[name, 'provider']}
                                                        label={t('llm.providerLabel')}
                                                        rules={[{ required: true, message: t('llm.providerPlaceholder') }]}
                                                    >
                                                        <Select
                                                            placeholder={t('llm.providerPlaceholder')}
                                                            options={[
                                                                { value: LLMProviderType.OPENAI, label: 'OpenAI' },
                                                                { value: LLMProviderType.DEEPSEEK, label: 'DeepSeek' },
                                                                { value: LLMProviderType.QWEN, label: 'Qwen' },
                                                                { value: LLMProviderType.ZHIPUAI, label: 'ZhipuAI' },
                                                                { value: LLMProviderType.SILICONFLOW, label: 'SiliconFlow' },
                                                                { value: LLMProviderType.VLLM, label: 'vLLM' },
                                                            ]}
                                                            onChange={(value) => {
                                                                setSelectedProviders(prev => ({
                                                                    ...prev,
                                                                    [name]: value
                                                                }));

                                                                const currentConfigs = form.getFieldValue('llm_configs');
                                                                if (currentConfigs && currentConfigs[name]) {
                                                                    const updatedConfig = { ...currentConfigs[name], model: undefined };
                                                                    const newConfigs = [...currentConfigs];
                                                                    newConfigs[name] = updatedConfig;
                                                                    form.setFieldsValue({ llm_configs: newConfigs });
                                                                }
                                                            }}
                                                        />
                                                    </Form.Item>
                                                </Col>

                                                <Col span={8}>
                                                    <Form.Item
                                                        {...restField}
                                                        name={[name, 'api_key']}
                                                        label={t('llm.apiKey')}
                                                        rules={[{ required: true, message: t('llm.apiKeyPlaceholder') }]}
                                                    >
                                                        <Input.Password placeholder={t('llm.apiKeyPlaceholder')} />
                                                    </Form.Item>
                                                </Col>

                                                <Col span={8}>
                                                    {typeof selectedProviders[name] !== 'undefined' &&
                                                        selectedProviders[name].toString() === LLMProviderType.VLLM.toString() ? (
                                                        <>
                                                            <Form.Item
                                                                {...restField}
                                                                name={[name, 'model']}
                                                                label={t('llm.model')}
                                                                rules={[{ required: true, message: t('llm.vllmModelPlaceholder') }]}
                                                            >
                                                                <Input placeholder={t('llm.vllmModelPlaceholder')} />
                                                            </Form.Item>
                                                        </>
                                                    ) : (
                                                        <Form.Item
                                                            {...restField}
                                                            name={[name, 'model']}
                                                            label={t('llm.model')}
                                                            rules={[{ required: true, message: t('llm.modelPlaceholder') }]}
                                                        >
                                                            <Select
                                                                placeholder={t('llm.modelPlaceholder')}
                                                                options={
                                                                    selectedProviders[name] && providerModels[selectedProviders[name]]
                                                                        ? providerModels[selectedProviders[name]]
                                                                        : []
                                                                }
                                                            />
                                                        </Form.Item>
                                                    )}
                                                </Col>
                                            </Row>
                                            {
                                                typeof selectedProviders[name] !== 'undefined' &&
                                                    selectedProviders[name].toString() === LLMProviderType.VLLM.toString() ?
                                                    (
                                                        <Row>
                                                            <Col span={24}>
                                                                <Form.Item
                                                                    {...restField}
                                                                    name={[name, 'base_url']}
                                                                    label={t('llm.baseUrl')}
                                                                >
                                                                    <Input placeholder={t('llm.baseUrlPlaceholder')} />
                                                                </Form.Item>
                                                            </Col>
                                                        </Row>
                                                    ) : <></>
                                            }
                                        </Card>
                                    ))}
                                    <Form.Item>
                                        <Button
                                            type="dashed"
                                            onClick={() => add({})}
                                            block
                                            icon={<PlusOutlined />}
                                        >
                                            {t('llm.addProvider')}
                                        </Button>
                                    </Form.Item>
                                </>
                            )}
                        </Form.List>
                    </Card>
                </Form>
            </Modal>
        </Card>
    );
};

export default LLM;
