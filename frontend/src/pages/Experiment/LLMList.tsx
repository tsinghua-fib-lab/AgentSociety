import React, { useState, useEffect } from 'react';
import { Table, Button, Card, Space, Modal, message, Tooltip, Input, Popconfirm, Form } from 'antd';
import { PlusOutlined, EditOutlined, DeleteOutlined, CopyOutlined, ExportOutlined } from '@ant-design/icons';
import LLMForm from './LLMForm';
import { ConfigItem } from '../../services/storageService';
import { Config, LLMConfig } from '../../types/config';
import { fetchCustom } from '../../components/fetch';
import dayjs from 'dayjs';

const LLMList: React.FC = () => {
    const [llms, setLLMs] = useState<ConfigItem[]>([]);
    const [loading, setLoading] = useState(false);
    const [searchText, setSearchText] = useState('');
    const [isModalVisible, setIsModalVisible] = useState(false);
    const [currentLLM, setCurrentLLM] = useState<ConfigItem | null>(null);
    const [formValues, setFormValues] = useState<{ llm_configs: LLMConfig[] }>({ llm_configs: [] });
    const [metaForm] = Form.useForm();

    // Load LLM configurations
    const loadLLMs = async () => {
        setLoading(true);
        try {
            const res = await fetchCustom('/api/llm-configs');
            if (!res.ok) {
                throw new Error('Failed to fetch LLM configurations');
            }
            const data = (await res.json()).data;
            setLLMs(data);
        } catch (error) {
            message.error(`Failed to load LLMs: ${JSON.stringify(error)}`, 3);
            console.error(error);
        } finally {
            setLoading(false);
        }
    };

    // Initialize data
    useEffect(() => {
        const init = async () => {
            await loadLLMs();
        };
        init();
    }, []);

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
        metaForm.setFieldsValue({
            name: `LLM ${llms.length + 1}`,
            description: ''
        });
        setIsModalVisible(true);
    };

    // Handle edit LLM
    const handleEdit = (llm: ConfigItem) => {
        setCurrentLLM(llm);
        setFormValues({
            llm_configs: llm.config
        });
        metaForm.setFieldsValue({
            name: llm.name,
            description: llm.description
        });
        setIsModalVisible(true);
    };

    // Handle duplicate LLM
    const handleDuplicate = (llm: ConfigItem) => {
        setCurrentLLM(null);
        setFormValues({
            llm_configs: llm.config
        });
        metaForm.setFieldsValue({
            name: `${llm.name} (Copy)`,
            description: llm.description
        });
        setIsModalVisible(true);
    };

    // Handle delete LLM
    const handleDelete = async (id: string) => {
        try {
            const res = await fetchCustom(`/api/llm-configs/${id}`, {
                method: 'DELETE'
            });
            if (!res.ok) {
                throw new Error('Failed to delete LLM config');
            }
            message.success('LLM config deleted successfully');
            loadLLMs();
        } catch (error) {
            message.error(`Failed to delete LLM config: ${JSON.stringify(error)}`, 3);
            console.error(error);
        }
    };

    // Handle export LLM
    const handleExport = (llm: ConfigItem) => {
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
            // Validate meta form
            const metaValues = await metaForm.validateFields();

            const configData = {
                name: metaValues.name,
                description: metaValues.description || '',
                config: formValues.llm_configs,
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
                throw new Error('Failed to save LLM config');
            }

            message.success(`LLM config ${currentLLM ? 'updated' : 'created'} successfully`);
            setIsModalVisible(false);
            loadLLMs();
        } catch (error) {
            message.error(`LLM config ${currentLLM ? 'update' : 'create'} failed: ${JSON.stringify(error)}`, 3);
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
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            sorter: (a: ConfigItem, b: ConfigItem) => a.name.localeCompare(b.name)
        },
        {
            title: 'Description',
            dataIndex: 'description',
            key: 'description',
            ellipsis: true
        },
        {
            title: 'Last Updated',
            dataIndex: 'updatedAt',
            key: 'updatedAt',
            render: (text: string) => dayjs(text).format('YYYY-MM-DD HH:mm:ss'),
            sorter: (a: ConfigItem, b: ConfigItem) => dayjs(a.updatedAt).valueOf() - dayjs(b.updatedAt).valueOf()
        },
        {
            title: 'Actions',
            key: 'actions',
            render: (_: any, record: ConfigItem) => (
                <Space size="small">
                    <Tooltip title="Edit">
                        <Button icon={<EditOutlined />} size="small" onClick={() => handleEdit(record)} />
                    </Tooltip>
                    <Tooltip title="Duplicate">
                        <Button icon={<CopyOutlined />} size="small" onClick={() => handleDuplicate(record)} />
                    </Tooltip>
                    <Tooltip title="Export">
                        <Button icon={<ExportOutlined />} size="small" onClick={() => handleExport(record)} />
                    </Tooltip>
                    <Tooltip title="Delete">
                        <Popconfirm
                            title="Are you sure you want to delete this LLM config?"
                            onConfirm={() => handleDelete(record.id)}
                            okText="Yes"
                            cancelText="No"
                        >
                            <Button icon={<DeleteOutlined />} size="small" danger />
                        </Popconfirm>
                    </Tooltip>
                </Space>
            )
        }
    ];

    return (
        <Card
            title="LLM Configurations"
            extra={<Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>Create New</Button>}
        >
            <Input.Search
                placeholder="Search LLM configs"
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
                title={currentLLM ? "Edit LLM Config" : "Create LLM Config"}
                open={isModalVisible}
                onOk={handleModalOk}
                onCancel={handleModalCancel}
                width={800}
                destroyOnClose
            >
                <Card title="Configuration Metadata" style={{ marginBottom: 16 }}>
                    <Form
                        form={metaForm}
                        layout="vertical"
                    >
                        <Form.Item
                            name="name"
                            label="Name"
                            rules={[{ required: true, message: 'Please enter a name for this configuration' }]}
                        >
                            <Input placeholder="Enter configuration name" />
                        </Form.Item>
                        <Form.Item
                            name="description"
                            label="Description"
                        >
                            <Input.TextArea
                                rows={2}
                                placeholder="Enter a description for this configuration"
                            />
                        </Form.Item>
                    </Form>
                </Card>

                <Card title="LLM Config Settings">
                    <LLMForm
                        value={formValues}
                        onChange={setFormValues}
                    />
                </Card>
            </Modal>
        </Card>
    );
};

export default LLMList;
