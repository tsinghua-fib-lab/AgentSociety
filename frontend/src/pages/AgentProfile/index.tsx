import { useAsyncResource } from '../../hooks/useAsyncResource';
import React, { useState, useCallback } from 'react';
import { Table, Button, Card, Space, Modal, message, Tooltip, Input, Popconfirm, Upload, Alert } from 'antd';
import { DeleteOutlined, DownloadOutlined, UploadOutlined, InfoCircleOutlined } from '@ant-design/icons';
import { fetchCustom } from '../../components/fetch';
import dayjs from 'dayjs';
import { useTranslation } from 'react-i18next';
import { ApiAgentProfile } from '../../types/profile';

const ProfileList: React.FC = () => {
    const { t } = useTranslation();
    const [searchText, setSearchText] = useState('');
    const [uploadModalVisible, setUploadModalVisible] = useState(false);
    const [uploading, setUploading] = useState(false);
    const [fileList, setFileList] = useState([]);
    const [description, setDescription] = useState('');

    // Load profiles
    const loadResource = useCallback(async (): Promise<ApiAgentProfile[]> => {
        const response = await fetchCustom('/api/agent-profiles');
        if (!response.ok) throw new Error(await response.text());
        const data = await response.json();
        return data.data || [];
    }, []);
    const handleLoadError = useCallback((error: unknown) => {
        console.error('Failed to load profiles:', error);
        message.error(t('profile.messages.loadFailed'));
    }, [t]);
    const { data: profiles, loading, reload: loadProfiles } = useAsyncResource(
        loadResource, handleLoadError, [],
    );

    // Handle search
    const handleSearch = (e) => {
        setSearchText(e.target.value);
    };

    // Filter profiles based on search text
    const filteredProfiles = profiles.filter(profile =>
        profile.name.toLowerCase().includes(searchText.toLowerCase())
    );

    // Handle profile download
    const handleDownload = async (profileId, profileName) => {
        try {
            // Call the API to get profile data
            const response = await fetchCustom(`/api/agent-profiles/${profileId}`);

            if (!response.ok) {
                throw new Error(`Failed to fetch profile: ${response.statusText}`);
            }

            const data = await response.json();

            if (data && data.data) {
                // 创建 JSON 格式的 blob
                const jsonContent = JSON.stringify(data.data, null, 2); // 使用 2 空格缩进，使输出更易读
                const blob = new Blob([jsonContent], { type: 'application/json' });
                const url = URL.createObjectURL(blob);
                const link = document.createElement('a');
                link.href = url;
                link.setAttribute('download', `${profileName}`);
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
                URL.revokeObjectURL(url); // 清理创建的 URL
            } else {
                message.warning(t('profile.messages.noData'));
            }
        } catch (error) {
            console.error('Failed to download profile:', error);
            message.error(t('profile.messages.loadFailed'));
        }
    };

    // Handle profile delete
    const handleDelete = async (profileId) => {
        try {
            const response = await fetchCustom(`/api/agent-profiles/${profileId}`, {
                method: 'DELETE',
            });

            if (!response.ok) {
                throw new Error(`Failed to delete profile: ${response.statusText}`);
            }

            message.success(t('profile.messages.deleteSuccess'));
            loadProfiles(); // Refresh the list
        } catch (error) {
            console.error('Failed to delete profile:', error);
            message.error(t('profile.messages.deleteFailed'));
        }
    };

    // Handle file upload
    const handleUpload = async () => {
        if (fileList.length === 0) {
            message.warning(t('profile.pleaseSelectFile'));
            return;
        }

        const formData = new FormData();
        formData.append('file', fileList[0].originFileObj as File);
        formData.append('name', fileList[0].name);
        if (description) {
            formData.append('description', description);
        }

        setUploading(true);

        try {
            const response = await fetchCustom('/api/agent-profiles/upload', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || `Upload failed: ${response.statusText}`);
            }

            setFileList([]);
            setDescription('');
            setUploadModalVisible(false);
            message.success(t('profile.messages.uploadSuccess'));
            await loadProfiles(); // Refresh the list
        } catch (error) {
            console.error('Failed to upload profile:', error);
            message.error(error instanceof Error ? error.message : t('profile.messages.uploadFailed'));
        } finally {
            setUploading(false);
        }
    };

    // Handle file change
    const handleFileChange = ({ fileList }) => {
        setFileList(fileList);
    };

    // Define table columns
    const columns = [
        {
            title: t('profile.table.name'),
            dataIndex: 'name',
            key: 'name',
        },
        {
            title: t('profile.table.description'),
            dataIndex: 'description',
            key: 'description',
            ellipsis: true,
        },
        {
            title: t('profile.table.count'),
            dataIndex: 'record_count',
            key: 'record_count',
        },
        {
            title: t('profile.table.createdAt'),
            dataIndex: 'created_at',
            key: 'created_at',
            render: (date: string) => date ? dayjs(date).format('YYYY-MM-DD HH:mm:ss') : '',
        },
        {
            title: t('common.actions'),
            key: 'actions',
            render: (_, record) => (
                <Space>
                    <Tooltip title={t('profile.table.download')}>
                        <Button
                            icon={<DownloadOutlined />}
                            size="small"
                            onClick={() => handleDownload(record.id, record.name)}
                        />
                    </Tooltip>
                    {
                        (record.tenant_id ?? '') !== '' && (
                            <Tooltip title={t('profile.table.delete')}>
                                <Popconfirm
                                    title={t('profile.messages.deleteConfirm')}
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
            ),
        },
    ];

    return (
        <Card
            title={t('profile.title')}
            extra={
                <Space>
                    <Button
                        type="primary"
                        icon={<UploadOutlined />}
                        onClick={() => setUploadModalVisible(true)}
                    >
                        {t('profile.uploadProfile')}
                    </Button>
                </Space>
            }
        >
            {/* 文档链接提示 */}
            <Alert
                message={
                    <Space size={4}>
                        <InfoCircleOutlined />
                        {t('profile.documentationTip')}
                        <a 
                            href="https://agentsociety.readthedocs.io/en/latest/02-development-guide/02-profile.html" 
                            target="_blank" 
                            rel="noopener noreferrer"
                        >
                            {t('profile.documentationLink')}
                        </a>
                    </Space>
                }
                type="info"
                showIcon={false}
                style={{ marginBottom: 16 }}
            />

            <Input.Search
                placeholder={t('profile.searchPlaceholder')}
                onChange={handleSearch}
                style={{ marginBottom: 16 }}
            />

            <Table
                columns={columns}
                dataSource={filteredProfiles}
                rowKey="id"
                loading={loading}
                pagination={{ pageSize: 10 }}
            />

            {/* Upload Modal */}
            <Modal
                title={t('profile.uploadTitle')}
                open={uploadModalVisible}
                onCancel={() => {
                    setUploadModalVisible(false);
                    setFileList([]);
                    setDescription('');
                }}
                footer={[
                    <Button key="cancel" onClick={() => {
                        setUploadModalVisible(false);
                        setFileList([]);
                        setDescription('');
                    }}>
                        {t('profile.cancel')}
                    </Button>,
                    <Button
                        key="upload"
                        type="primary"
                        onClick={handleUpload}
                        loading={uploading}
                        disabled={fileList.length === 0}
                    >
                        {t('profile.upload')}
                    </Button>
                ]}
            >
                <Space direction="vertical" style={{ width: '100%' }}>
                    <Upload.Dragger
                        fileList={fileList}
                        onChange={handleFileChange}
                        beforeUpload={() => false}
                        multiple={false}
                        // accept=".csv,.json"
                        accept=".json"
                    >
                        <p className="ant-upload-drag-icon">
                            <UploadOutlined />
                        </p>
                        <p className="ant-upload-text">{t('profile.uploadHint')}</p>
                        <p className="ant-upload-hint">
                            {t('profile.uploadDescription')}
                        </p>
                    </Upload.Dragger>
                    <Input.TextArea
                        placeholder={t('profile.enterDescription')}
                        value={description}
                        onChange={(e) => setDescription(e.target.value)}
                        rows={4}
                    />
                </Space>
            </Modal>
        </Card>
    );
};

export default ProfileList; 