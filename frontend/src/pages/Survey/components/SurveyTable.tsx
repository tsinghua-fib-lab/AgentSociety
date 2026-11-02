import { useAsyncResource } from '../../../hooks/useAsyncResource';
import React, { useState, useCallback } from 'react';
import { Table, Button, Modal, Form, Input, Space, Flex, Popconfirm, Dropdown, Tabs, App } from 'antd';
import dayjs from 'dayjs';
import 'survey-core/survey-core.min.css';
import { useForm } from 'antd/lib/form/Form';
import { EllipsisOutlined } from '@ant-design/icons';
import { Editor } from '../../../components/Editor';
import { Survey } from '../../../components/type';
import { fetchCustom } from '../../../components/fetch';
import { useTranslation } from 'react-i18next';
import SurveyBuilder from './SurveyBuilder';

interface EditingSurvey {
    id: string;
    name: string;
    data: string;
}

const EmptySurvey: EditingSurvey = {
    id: '',
    name: '',
    data: '',
};

const SurveyTableInner = () => {
    const { t } = useTranslation();
    const { message } = App.useApp();
    const [open, setOpen] = useState(false);
    const [editingSurvey, setEditingSurvey] = useState<EditingSurvey>(EmptySurvey);
    const [form] = useForm();
    const [activeTab, setActiveTab] = useState('builder');
    const [formValues, setFormValues] = useState({ name: '', data: '' });

    const loadResource = useCallback(async (): Promise<Survey[]> => {
        const response = await fetchCustom('/api/surveys');
        if (!response.ok) throw new Error(await response.text());
        const data = await response.json();
        return data.data || [];
    }, []);
    const handleLoadError = useCallback((error: unknown) => {
        console.error('Failed to load surveys:', error);
        message.error(`${t('survey.fetchFailed')} ${error}`);
    }, [message, t]);
    const { data: surveys, reload: fetchSurveys } = useAsyncResource(
        loadResource, handleLoadError, [],
    );

    const handleDelete = async (id) => {
        try {
            const res = await fetchCustom(`/api/surveys/${id}`, { method: 'DELETE' });
            if (!res.ok) {
                const errMessage = await res.text();
                throw new Error(errMessage);
            }
            message.success(t('survey.deleteSuccess'));
            await fetchSurveys();
        } catch (err) {
            message.error(`${t('survey.deleteFailed')} ${err}`);
        }
    };

    const handleEdit = (survey) => {
        const jsonData = JSON.stringify(survey.data, null, 2);
        const editingSurveyData = {
            id: survey.id,
            name: survey.name,
            data: jsonData,
        };
        
        setEditingSurvey(editingSurveyData);
        setFormValues({ name: survey.name, data: jsonData });
        form.setFieldsValue({ name: survey.name, data: jsonData });
        setActiveTab('builder'); // 默认打开可视化建构器
        setOpen(true);
    };

    const handleCreate = () => {
        const defaultJsonData = JSON.stringify({
            pages: [
                {
                    name: 'page1',
                    elements: []
                }
            ]
        }, null, 2);
        
        const newSurvey = {
            id: '',
            name: '',
            data: defaultJsonData,
        };
        
        setEditingSurvey(newSurvey);
        setFormValues({ name: '', data: defaultJsonData });
        form.setFieldsValue({ name: '', data: defaultJsonData });
        setActiveTab('builder');
        setOpen(true);
    };

    const handleSubmit = async (values) => {
        if (editingSurvey.id !== '') {
            try {
                const res = await fetchCustom(`/api/surveys/${editingSurvey.id}`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        name: values.name,
                        data: JSON.parse(values.data),
                    }),
                });
                if (!res.ok) {
                    const errMessage = await res.text();
                    throw new Error(errMessage);
                }
                message.success(t('survey.updateSuccess'));
                setOpen(false);
                form.resetFields();
                setFormValues({ name: '', data: '' });
                setEditingSurvey(EmptySurvey);
                await fetchSurveys();
            } catch (err) {
                message.error(`${t('survey.updateFailed')} ${err}`);
            }
        } else {
            try {
                const res = await fetchCustom('/api/surveys', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        name: values.name,
                        data: JSON.parse(values.data),
                    }),
                });
                if (!res.ok) {
                    const errMessage = await res.text();
                    throw new Error(errMessage);
                }
                message.success(t('survey.createSuccess'));
                setOpen(false);
                form.resetFields();
                setFormValues({ name: '', data: '' });
                setEditingSurvey(EmptySurvey);
                await fetchSurveys();
            } catch (err) {
                message.error(`${t('survey.createFailed')} ${err}`);
            }
        }
    };

    const handleModalCancel = () => {
        setOpen(false);
        // 重置表单和状态
        form.resetFields();
        setFormValues({ name: '', data: '' });
        setEditingSurvey(EmptySurvey);
    };

    const tableColumns = [
        { title: t('survey.table.id'), dataIndex: 'id', width: '13%' },
        { title: t('survey.table.name'), dataIndex: 'name', width: '7%' },
        {
            title: t('survey.table.data'),
            dataIndex: 'data',
            width: '55%',
            ellipsis: true,
            render: (text) => JSON.stringify(text, null, 2),
        },
        {
            title: t('survey.table.createdAt'),
            dataIndex: 'created_at',
            width: '10%',
            render: (date) => dayjs(date).format('YYYY-MM-DD HH:mm:ss'),
        },
        {
            title: t('survey.table.updatedAt'),
            dataIndex: 'updated_at',
            width: '10%',
            render: (date) => dayjs(date).format('YYYY-MM-DD HH:mm:ss'),
        },
        {
            title: t('survey.table.action'),
            key: 'action',
            width: '15%',
            render: (record) => (
                <Space size="middle">
                    <Button type="primary" onClick={() => handleEdit(record)}
                    >{t('survey.table.edit')}</Button>
                    <Dropdown
                        menu={{
                            items: [
                                {
                                    key: 'delete',
                                    label: (
                                        <Popconfirm
                                            title={t('survey.deleteConfirm')}
                                            onConfirm={() => handleDelete(record.id)}
                                        >
                                            <span style={{ color: '#ff4d4f' }}>{t('survey.table.delete')}</span>
                                        </Popconfirm>
                                    )
                                }
                            ]
                        }}
                    >
                        <Button icon={<EllipsisOutlined />} />
                    </Dropdown>
                </Space>
            ),
        },
    ];

    return (
        <>
            <Flex vertical style={{ margin: "16px" }}>
                <Flex justify='end'>
                    <Button type="primary" onClick={handleCreate} style={{ marginBottom: 16 }}>
                        {t('survey.createSurvey')}
                    </Button>
                </Flex>
                <Table dataSource={surveys} columns={tableColumns} rowKey="id" />
                <Modal
                    open={open}
                    width='80vw'
                    title={editingSurvey.id ? t('survey.editSurvey') : t('survey.createSurvey')}
                    onCancel={handleModalCancel}
                    footer={null}
                >
                    <Tabs 
                        activeKey={activeTab} 
                        onChange={setActiveTab}
                        items={[
                            {
                                key: 'builder',
                                label: t('survey.visualBuilder'),
                                children: (
                                    <Flex>
                                        <div style={{ width: '100%' }}>
                                            <Form
                                                form={form}
                                                layout="vertical"
                                                onValuesChange={(changedValues, allValues) => {
                                                    // 只在真正有变化时更新，避免无限循环
                                                    if (JSON.stringify(allValues) !== JSON.stringify(formValues)) {
                                                        setFormValues(allValues);
                                                    }
                                                }}
                                                onFinish={handleSubmit}
                                            >
                                                <Form.Item label={t('survey.surveyName')} name="name" rules={[
                                                    { required: true, message: t('survey.pleaseInputName') },
                                                ]}>
                                                    <Input />
                                                </Form.Item>
                                                {/* 隐藏的data字段，用于存储JSON数据 */}
                                                <Form.Item name="data" style={{ display: 'none' }}>
                                                    <Input type="hidden" />
                                                </Form.Item>
                                                <div style={{ maxHeight: '50vh', overflow: 'auto' }}>
                                                    <SurveyBuilder
                                                        value={formValues.data}
                                                        onChange={(value) => {
                                                            form.setFieldValue('data', value);
                                                            setFormValues(prev => ({ ...prev, data: value }));
                                                        }}
                                                    />
                                                </div>
                                                <Button type="primary" htmlType='submit' style={{ marginTop: 8 }}>
                                                    {t('survey.submit')}
                                                </Button>
                                            </Form>
                                        </div>
                                        {/* <div style={{ overflow: 'auto', maxHeight: '60vh', width: '50%' }}>
                                            <SurveyUI model={model} />
                                        </div> */}
                                    </Flex>
                                )
                            },
                            {
                                key: 'json',
                                label: t('survey.jsonEditor'),
                                children: (
                                    <Flex>
                        <Form
                            form={form}
                            style={{ width: '100%' }}
                            layout="vertical"
                                                                        onValuesChange={(changedValues, allValues) => {
                                // 只在真正有变化时更新，避免无限循环
                                if (JSON.stringify(allValues) !== JSON.stringify(formValues)) {
                                    setFormValues(allValues);
                                    setEditingSurvey({
                                        ...editingSurvey,
                                        ...changedValues,
                                    });
                                }
                            }}
                            onFinish={handleSubmit}
                        >
                            <Form.Item label={t('survey.surveyName')} name="name" rules={[
                                { required: true, message: t('survey.pleaseInputName') },
                            ]}>
                                <Input />
                            </Form.Item>
                            <Form.Item
                                label={<span>{t('survey.surveyJsonData')} {/* ({t('survey.onlineVisualEditor')}&nbsp;<ExportOutlined onClick={handleJsonButton} />&nbsp;) */}</span>}
                                name="data"
                                rules={[
                                    { required: true, message: t('survey.pleaseInputData') },
                                    {    
                                        validator: (_, value) => {
                                            try {
                                                JSON.parse(value);
                                                return Promise.resolve();
                                            } catch {
                                                return Promise.reject(new Error(t('survey.invalidJson')));
                                            }
                                        }
                                    },
                                ]}
                            >
                                <Editor
                                    width="100%"
                                    height="50vh"
                                    language="json"
                                    defaultValue=''
                                    value={form.getFieldValue('data') || ''}
                                    onChange={(value) => form.setFieldValue('data', value)}
                                />
                            </Form.Item>
                            <Button type="primary" htmlType='submit' style={{ marginTop: 8 }}>
                                {t('survey.submit')}
                            </Button>
                        </Form>
                        {/* <div style={{ overflow: 'auto', maxHeight: '60vh', width: '50%' }}>
                            <SurveyUI model={model} />
                        </div> */}
                    </Flex>
                                )
                            }
                        ]}
                    />
                </Modal>
            </Flex>
        </>
    );
};

const SurveyTable = () => {
    return (
        <App>
            <SurveyTableInner />
        </App>
    );
};

export default SurveyTable;