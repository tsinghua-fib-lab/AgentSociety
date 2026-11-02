import React, { useState, useMemo } from 'react';
import { Card, Button, Form, Input, Select, Space, List, Modal, InputNumber, Typography, Row, Col, Tag, Popconfirm } from 'antd';
import { PlusOutlined, DeleteOutlined, EditOutlined, ArrowUpOutlined, ArrowDownOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';

const { Text } = Typography;
const { Option } = Select;

interface Choice {
    value: string;
    text: string;
}

interface Question {
    name: string;
    title: string;
    type: 'text' | 'radiogroup' | 'checkbox' | 'rating';
    choices?: Choice[];
    rateMin?: number;
    rateMax?: number;
    rateStep?: number;
}

interface QuestionFormValues {
    name?: string;
    title: string;
    type: Question['type'];
    choices?: string[];
    rateMin?: number;
    rateMax?: number;
    rateStep?: number;
}

interface SurveyBuilderProps {
    value?: string;
    onChange?: (value: string) => void;
}

const SurveyBuilder: React.FC<SurveyBuilderProps> = ({ value, onChange }) => {
    const { t } = useTranslation();

    // const [surveyTitle, setSurveyTitle] = useState('');
    // const [surveyDescription, setSurveyDescription] = useState('');
    const [isModalVisible, setIsModalVisible] = useState(false);
    const [editingQuestion, setEditingQuestion] = useState<Question | null>(null);
    const [editingIndex, setEditingIndex] = useState<number>(-1);
    const [form] = Form.useForm();
    const [localValue, setLocalValue] = useState('');
    const jsonValue = value ?? localValue;
    const survey = useMemo(() => {
        try {
            const parsed = JSON.parse(jsonValue || '{}');
            return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
        } catch {
            return {};
        }
    }, [jsonValue]);
    const pages = Array.isArray(survey.pages) ? survey.pages : [];
    const questions: Question[] = Array.isArray(pages[0]?.elements) ? pages[0].elements : [];

    // Notify the parent only for user edits. Prop changes are rendered directly.
    const setQuestions = (nextQuestions: Question[]) => {
        const json = JSON.stringify({
            ...survey,
            pages: [
                { ...pages[0], name: pages[0]?.name ?? 'page1', elements: nextQuestions },
                ...pages.slice(1),
            ],
        }, null, 2);
        if (value === undefined) setLocalValue(json);
        onChange?.(json);
    };

    const showQuestionModal = (question?: Question, index?: number) => {
        if (question && index !== undefined) {
            setEditingQuestion(question);
            setEditingIndex(index);
            form.setFieldsValue({
                ...question,
                choices: question.choices?.map(c => c.text) || []
            });
        } else {
            setEditingQuestion(null);
            setEditingIndex(-1);
            form.resetFields();
        }
        setIsModalVisible(true);
    };

    const handleQuestionSubmit = (values: QuestionFormValues) => {
        const newQuestion: Question = {
            name: values.name || `question_${Date.now()}`,
            title: values.title,
            type: values.type,
        };

        // 根据问题类型添加特定字段
        if (values.type === 'radiogroup' || values.type === 'checkbox') {
            newQuestion.choices = values.choices?.map((text: string, index: number) => ({
                value: `choice_${index + 1}`,
                text: text.trim()
            })).filter((choice: Choice) => choice.text) || [];
        } else if (values.type === 'rating') {
            newQuestion.rateMin = values.rateMin || 1;
            newQuestion.rateMax = values.rateMax || 5;
            newQuestion.rateStep = values.rateStep || 1;
        }

        const newQuestions = [...questions];
        if (editingIndex >= 0) {
            newQuestions[editingIndex] = newQuestion;
        } else {
            newQuestions.push(newQuestion);
        }
        
        setQuestions(newQuestions);
        setIsModalVisible(false);
        form.resetFields();
    };

    const deleteQuestion = (index: number) => {
        const newQuestions = questions.filter((_, i) => i !== index);
        setQuestions(newQuestions);
    };

    const moveQuestion = (index: number, direction: 'up' | 'down') => {
        const newQuestions = [...questions];
        const targetIndex = direction === 'up' ? index - 1 : index + 1;
        
        if (targetIndex >= 0 && targetIndex < questions.length) {
            [newQuestions[index], newQuestions[targetIndex]] = [newQuestions[targetIndex], newQuestions[index]];
            setQuestions(newQuestions);
        }
    };

    const getQuestionTypeText = (type: string) => {
        const typeMap = {
            text: t('survey.builder.questionTypes.text'),
            radiogroup: t('survey.builder.questionTypes.radiogroup'),
            checkbox: t('survey.builder.questionTypes.checkbox'),
            rating: t('survey.builder.questionTypes.rating')
        };
        return typeMap[type] || type;
    };

    return (
        <div>
            {/* <Card title="问卷基本信息" style={{ marginBottom: 16 }}>
                <Row gutter={16}>
                    <Col span={12}>
                        <Form.Item label="问卷标题">
                            <Input
                                value={surveyTitle}
                                onChange={(e) => setSurveyTitle(e.target.value)}
                                placeholder="请输入问卷标题"
                            />
                        </Form.Item>
                    </Col>
                    <Col span={12}>
                        <Form.Item label="问卷描述">
                            <Input
                                value={surveyDescription}
                                onChange={(e) => setSurveyDescription(e.target.value)}
                                placeholder="请输入问卷描述"
                            />
                        </Form.Item>
                    </Col>
                </Row>
            </Card> */}

            <Card 
                title={t('survey.builder.questionList')}
                extra={
                    <Button type="primary" icon={<PlusOutlined />} onClick={() => showQuestionModal()}>
                        {t('survey.builder.addQuestion')}
                    </Button>
                }
            >
                <List
                    dataSource={questions}
                    renderItem={(item, index) => (
                        <List.Item
                            actions={[
                                <Button
                                    key="up"
                                    size="small"
                                    icon={<ArrowUpOutlined />}
                                    disabled={index === 0}
                                    onClick={() => moveQuestion(index, 'up')}
                                />,
                                <Button
                                    key="down"
                                    size="small"
                                    icon={<ArrowDownOutlined />}
                                    disabled={index === questions.length - 1}
                                    onClick={() => moveQuestion(index, 'down')}
                                />,
                                <Button
                                    key="edit"
                                    size="small"
                                    icon={<EditOutlined />}
                                    onClick={() => showQuestionModal(item, index)}
                                />,
                                <Popconfirm
                                    key="delete"
                                    title={t('survey.builder.deleteConfirm')}
                                    onConfirm={() => deleteQuestion(index)}
                                >
                                    <Button size="small" danger icon={<DeleteOutlined />} />
                                </Popconfirm>
                            ]}
                        >
                            <List.Item.Meta
                                title={
                                    <Space>
                                        <Text strong>{item.title}</Text>
                                        <Tag color="blue">{getQuestionTypeText(item.type)}</Tag>
                                    </Space>
                                }
                                description={
                                    <div>
                                        {item.type === 'radiogroup' || item.type === 'checkbox' ? (
                                            <Text type="secondary">
                                                {t('survey.builder.choices')}: {item.choices?.map(c => c.text).join(', ')}
                                            </Text>
                                        ) : item.type === 'rating' ? (
                                            <Text type="secondary">
                                                {t('survey.builder.ratingRange')}: {item.rateMin} - {item.rateMax}
                                            </Text>
                                        ) : null}
                                    </div>
                                }
                            />
                        </List.Item>
                    )}
                />
                {questions.length === 0 && (
                    <div style={{ textAlign: 'center', padding: '40px 0', color: '#999' }}>
                        {t('survey.builder.noQuestions')}
                    </div>
                )}
            </Card>

            <Modal
                title={editingQuestion ? t('survey.builder.editQuestion') : t('survey.builder.addQuestion')}
                open={isModalVisible}
                onCancel={() => setIsModalVisible(false)}
                footer={null}
                width={600}
            >
                <Form
                    form={form}
                    layout="vertical"
                    onFinish={handleQuestionSubmit}
                >
                    <Form.Item
                        name="title"
                        label={t('survey.builder.questionTitle')}
                        rules={[{ required: true, message: t('survey.builder.pleaseInputQuestionTitle') }]}
                    >
                        <Input placeholder={t('survey.builder.pleaseInputQuestionTitle')} />
                    </Form.Item>

                    <Form.Item
                        name="type"
                        label={t('survey.builder.questionType')}
                        rules={[{ required: true, message: t('survey.builder.pleaseSelectQuestionType') }]}
                    >
                        <Select placeholder={t('survey.builder.selectQuestionType')}>
                            <Option value="text">{t('survey.builder.questionTypes.text')}</Option>
                            <Option value="radiogroup">{t('survey.builder.questionTypes.radiogroup')}</Option>
                            <Option value="checkbox">{t('survey.builder.questionTypes.checkbox')}</Option>
                            <Option value="rating">{t('survey.builder.questionTypes.rating')}</Option>
                        </Select>
                    </Form.Item>

                    <Form.Item noStyle shouldUpdate={(prevValues, currentValues) => prevValues.type !== currentValues.type}>
                        {({ getFieldValue }) => {
                            const questionType = getFieldValue('type');
                            
                            if (questionType === 'radiogroup' || questionType === 'checkbox') {
                                return (
                                    <Form.List name="choices">
                                        {(fields, { add, remove }) => (
                                            <>
                                                <Form.Item label={t('survey.builder.choices')}>
                                                    <Button type="dashed" onClick={() => add()} block icon={<PlusOutlined />}>
                                                        {t('survey.builder.addChoice')}
                                                    </Button>
                                                </Form.Item>
                                                {fields.map(({ key, name, ...restField }) => (
                                                    <div key={key} style={{ display: 'flex', marginBottom: 8, alignItems: 'center', gap: 8 }}>
                                                        <Form.Item
                                                            {...restField}
                                                            name={name}
                                                            style={{ flex: 1, marginBottom: 0 }}
                                                            rules={[{ required: true, message: t('survey.builder.pleaseInputChoiceContent') }]}
                                                        >
                                                            <Input placeholder={t('survey.builder.pleaseInputChoiceContent')} />
                                                        </Form.Item>
                                                        <DeleteOutlined 
                                                            onClick={() => remove(name)} 
                                                            style={{ color: '#ff4d4f', cursor: 'pointer' }}
                                                        />
                                                    </div>
                                                ))}
                                            </>
                                        )}
                                    </Form.List>
                                );
                            }
                            
                            if (questionType === 'rating') {
                                return (
                                    <Row gutter={16}>
                                        <Col span={8}>
                                            <Form.Item
                                                name="rateMin"
                                                label={t('survey.builder.minValue')}
                                                initialValue={1}
                                            >
                                                <InputNumber min={0} />
                                            </Form.Item>
                                        </Col>
                                        <Col span={8}>
                                            <Form.Item
                                                name="rateMax"
                                                label={t('survey.builder.maxValue')}
                                                initialValue={5}
                                            >
                                                <InputNumber min={1} />
                                            </Form.Item>
                                        </Col>
                                        <Col span={8}>
                                            <Form.Item
                                                name="rateStep"
                                                label={t('survey.builder.stepValue')}
                                                initialValue={1}
                                            >
                                                <InputNumber min={0.1} step={0.1} />
                                            </Form.Item>
                                        </Col>
                                    </Row>
                                );
                            }
                            
                            return null;
                        }}
                    </Form.Item>

                    <Form.Item>
                        <Space>
                            <Button type="primary" htmlType="submit">
                                {editingQuestion ? t('survey.builder.updateQuestion') : t('survey.builder.addQuestion')}
                            </Button>
                            <Button onClick={() => setIsModalVisible(false)}>
                                {t('survey.builder.cancel')}
                            </Button>
                        </Space>
                    </Form.Item>
                </Form>
            </Modal>
        </div>
    );
};

export default SurveyBuilder; 