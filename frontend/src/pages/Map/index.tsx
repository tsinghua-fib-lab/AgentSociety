import React, { useState, useEffect, useCallback } from 'react';
import { Table, Button, Card, Space, Modal, message, Tooltip, Input, Popconfirm, Form, Row, Col, Upload, Alert } from 'antd';
import {
    PlusOutlined,
    EditOutlined,
    DeleteOutlined,
    EyeOutlined,
    DownloadOutlined,
    InboxOutlined,
    InfoCircleOutlined
} from '@ant-design/icons';
import { MapConfig, ConfigWrapper } from '../../types/config';
import { fetchCustom, postDownloadCustom, WITH_AUTH } from '../../components/fetch';
import dayjs from 'dayjs';
import { getAccessToken } from '../../components/authState';
import { useTranslation } from 'react-i18next';

const { Dragger } = Upload;

const Map: React.FC = () => {
    const { t } = useTranslation();
    const [maps, setMaps] = useState<ConfigWrapper<MapConfig>[]>([]);
    const [loading, setLoading] = useState(false);
    const [searchText, setSearchText] = useState('');
    const [isModalVisible, setIsModalVisible] = useState(false);
    const [currentMap, setCurrentMap] = useState<ConfigWrapper<MapConfig> | null>(null);
    const [formValues, setFormValues] = useState<Partial<MapConfig>>({});
    const [metaForm] = Form.useForm();

    // Load map configurations
    const loadMaps = useCallback(async () => {
        setLoading(true);
        try {
            const res = await fetchCustom('/api/map-configs');
            if (!res.ok) {
                throw new Error(await res.text());
            }
            const data = (await res.json()).data;
            setMaps(data);
        } catch (error) {
            message.error(t('map.messages.loadFailed') + ': ' + JSON.stringify(error.message), 3);
            console.error(error);
        } finally {
            setLoading(false);
        }
    }, [t]);
    // Initialize data
    useEffect(() => {
        const init = async () => {
            await loadMaps();
        };
        init();
    }, [loadMaps]);

    // Handle search
    const handleSearch = (e: React.ChangeEvent<HTMLInputElement>) => {
        setSearchText(e.target.value);
    };

    // Filter maps based on search text
    const filteredMaps = maps.filter(map =>
        map.name.toLowerCase().includes(searchText.toLowerCase()) ||
        (map.description && map.description.toLowerCase().includes(searchText.toLowerCase()))
    );

    // Handle create new map
    const handleCreate = () => {
        setCurrentMap(null);
        // Create a basic map config based on config.json structure
        setFormValues({
            file_path: "maps/default_map.pb",
        });
        metaForm.setFieldsValue({
            name: `Map ${maps.length + 1}`,
            description: ''
        });
        setIsModalVisible(true);
    };

    // Handle edit map
    const handleEdit = (map: ConfigWrapper<MapConfig>) => {
        setCurrentMap(map);
        setFormValues(map.config);
        metaForm.setFieldsValue({
            name: map.name,
            description: map.description
        });
        setIsModalVisible(true);
    };

    // Handle delete map
    const handleDelete = async (id: string) => {
        try {
            const res = await fetchCustom(`/api/map-configs/${id}`, {
                method: 'DELETE'
            });
            if (!res.ok) {
                throw new Error(await res.text());
            }
            message.success(t('map.messages.deleteSuccess'));
            loadMaps();
        } catch (error) {
            message.error(t('map.messages.deleteFailed') + ': ' + JSON.stringify(error.message), 3);
            console.error(error);
        }
    };

    // Handle modal OK
    const handleModalOk = async () => {
        try {
            // Validate meta form
            const metaValues = await metaForm.validateFields();

            const configData: ConfigWrapper<MapConfig> = {
                name: metaValues.name,
                description: metaValues.description || '',
                config: formValues as MapConfig,
            };
            let res: Response;
            if (currentMap) {
                res = await fetchCustom(`/api/map-configs/${currentMap.id}`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(configData),
                });
            } else {
                res = await fetchCustom('/api/map-configs', {
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

            message.success(currentMap ? t('map.messages.updateSuccess') : t('map.messages.createSuccess'));
            setIsModalVisible(false);
            loadMaps();
        } catch (error) {
            message.error((currentMap ? t('map.messages.updateFailed') : t('map.messages.createFailed')) + ': ' + JSON.stringify(error.message), 3);
            console.error('Validation failed:', error);
        }
    };

    // Handle modal cancel
    const handleModalCancel = () => {
        setIsModalVisible(false);
    };

    // Update parent component state when form values change
    const handleValuesChange = (_changedValues: Record<string, unknown>, allValues: Record<string, unknown>) => {
        console.log('changedValues', _changedValues);
        console.log('allValues', allValues);
        const filePath = allValues.file_path as { file?: { status?: string; response?: { data?: { file_path?: string } } } } | undefined;
        const file = filePath?.file;
        if (file && file.status === 'done') {
            setFormValues({
                file_path: file.response.data.file_path,
            });
        } else {
            setFormValues({
                file_path: null,
            });
        }
    };

    const uploadProps = {
        name: 'file',
        multiple: false,
        action: '/api/map-configs/-/upload',
        headers: WITH_AUTH ? {
            Authorization: `Bearer ${getAccessToken()}`
        } : {},
        beforeUpload: (file) => {
            // check suffix
            if (!file.name.endsWith('.pb')) {
                message.error(t('map.messages.invalidFileType'));
                return false;
            }
            return true;
        },
        onChange(info) {
            const { status } = info.file;
            if (status === 'done') {
                message.success(t('map.messages.uploadSuccess'));
            } else if (status === 'error') {
                message.error(t('map.messages.uploadFailed'));
            }
        },
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
            render: (_: unknown, record: ConfigWrapper<MapConfig>) => (
                <Space size="small">
                    {
                        (record.tenant_id ?? '') !== '' && (
                            <Tooltip title={t('common.edit')}>
                                <Button icon={<EditOutlined />} size="small" onClick={() => handleEdit(record)} />
                            </Tooltip>
                        )
                    }
                    <Tooltip title={t('common.view')}>
                        <Button icon={<EyeOutlined />} size="small" onClick={async () => {
                            // get token
                            const url = `/api/map-configs/${record.id}/temp-link`
                            try {
                                const res = await fetchCustom(url, {
                                    method: 'POST',
                                    headers: {
                                        'Content-Type': 'application/json',
                                    },
                                    body: JSON.stringify({ expire_seconds: 600 }),
                                })
                                if (!res.ok) {
                                    throw new Error(await res.text());
                                }
                                const data = await res.json();
                                const token = data.data.token;
                                // create temp-link url
                                // format: ${window.location.origin}/api/map-configs/{config_id}/temp-link?token=${token}
                                const tempLinkUrl = `${window.location.origin}/api/map-configs/${record.id}/temp-link?token=${token}`;
                                // open in new tab
                                // format: https://moss.fiblab.net/tools/map-editor?dataSource=${tempLinkUrl}
                                window.open(`https://moss.fiblab.net/tools/map-editor?dataSource=${tempLinkUrl}`, '_blank');
                            } catch (error) {
                                message.error(`Failed to get temp link: ${JSON.stringify(error.message)}`, 3);
                                console.error(error);
                            }
                        }} />
                    </Tooltip>
                    <Tooltip title={t('common.export')}>
                        <Button icon={<DownloadOutlined />} size="small" onClick={() => {
                            postDownloadCustom(`/api/map-configs/${record.id}/export`)
                        }} />
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
            title={t('map.title')}
            extra={<Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>{t('map.createNew')}</Button>}
        >
            <Input.Search
                placeholder={t('map.searchPlaceholder')}
                onChange={handleSearch}
                style={{ marginBottom: 16 }}
            />

            <Table
                columns={columns}
                dataSource={filteredMaps}
                rowKey="id"
                loading={loading}
                pagination={{ pageSize: 10 }}
            />

            <Modal
                title={currentMap ? t('map.editTitle') : t('map.createTitle')}
                open={isModalVisible}
                onOk={handleModalOk}
                onCancel={handleModalCancel}
                width="80vw"
                destroyOnHidden
            >
                <Card title={t('common.metadataTitle')} style={{ marginBottom: 8 }}>
                    <Form
                        form={metaForm}
                        layout="vertical"
                    >
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
                    </Form>
                </Card>

                <Card title={t('map.settingsTitle')}>
                    <Alert
                        message={
                            <Space size={4}>
                                <InfoCircleOutlined />
                                {t('map.documentationHint')}
                                <a 
                                    href="https://agentsociety.readthedocs.io/en/latest/02-development-guide/03-map.html" 
                                    target="_blank" 
                                    rel="noopener noreferrer"
                                >
                                    {t('map.documentationLink')}
                                </a>
                            </Space>
                        }
                        type="info"
                        showIcon={false}
                        style={{ marginBottom: 16 }}
                    />
                    <Form
                        layout="vertical"
                        onValuesChange={handleValuesChange}
                        initialValues={formValues}
                    >
                        {currentMap && (
                            <Form.Item
                                label={t('map.currentFile')}
                            >
                                <Input value={currentMap.config.file_path} disabled />
                            </Form.Item>
                        )}
                        <Form.Item
                            name="file_path"
                            label={t('map.uploadTitle')}
                            required
                        >
                            <Dragger {...uploadProps} style={{ marginBottom: 16 }}>
                                <p className="ant-upload-drag-icon">
                                    <InboxOutlined />
                                </p>
                                <p className="ant-upload-text">{t('map.uploadHint')}</p>
                                <p className="ant-upload-hint">
                                    {t('map.uploadDescription')}
                                </p>
                            </Dragger>
                        </Form.Item>
                    </Form>
                </Card>
            </Modal>
        </Card>
    );
};

export default Map; 
