import { useAsyncResource } from '../../hooks/useAsyncResource';
import { useState, useCallback } from "react";
import { Card, Row, Col, Button, message, Space, Modal, InputNumber, Popconfirm } from "antd";
import { ProTable, ProColumns } from "@ant-design/pro-components";
import { ActionType } from "@ant-design/pro-table";
import { useRef } from "react";
import { useTranslation } from "react-i18next";
import { fetchCustom } from "../../components/fetch";
import { SyncOutlined } from "@ant-design/icons";

interface Account {
    id: string;
    balance: number;
    created_at: string;
    updated_at: string;
}

interface Bill {
    id: string;
    related_exp_id: string;
    item: string;
    amount: number;
    unit_price: number;
    quantity: number;
    description: string;
    created_at: string;
}

const Page = () => {
    const { t } = useTranslation();
    const [rechargeVisible, setRechargeVisible] = useState(false);
    const [rechargeAmount, setRechargeAmount] = useState<number>(100);
    const [paymentStatus, setPaymentStatus] = useState<'pending' | 'success' | 'failed'>('pending');
    const [paymentModalVisible, setPaymentModalVisible] = useState(false);
    const [paymentUrl, setPaymentUrl] = useState('');
    const actionRef = useRef<ActionType | undefined>(undefined);

    const presetAmounts = [10, 20, 50, 100, 1000];

    const loadResource = useCallback(async (): Promise<Account | null> => {
        const response = await fetchCustom('/api/account');
        if (!response.ok) throw new Error(await response.text());
        const data = await response.json();
        return data.data;
    }, []);
    const handleLoadError = useCallback((error: unknown) => {
        console.error('Failed to load account:', error);
        message.error(t('bill.fetchAccountFailed'));
    }, [t]);
    const { data: account, reload: fetchAccount } = useAsyncResource(
        loadResource, handleLoadError, null,
    );

    const checkPaymentStatus = async (id: string) => {
        try {
            const res = await fetchCustom(`/api/alipay/recharge/${id}`);
            if (res.ok) {
                const data = await res.json();
                if (data.data.status === 'success') {
                    setPaymentStatus('success');
                    message.success(t('bill.payment.success'));
                    setPaymentModalVisible(false);
                    fetchAccount();
                    actionRef.current?.reload();
                    return true;
                } else if (data.data.status === 'failed') {
                    setPaymentStatus('failed');
                    message.error(t('bill.payment.failed'));
                    setPaymentModalVisible(false);
                    return true;
                }
            }
            return false;
        } catch (_err) {
            message.error(t('bill.payment.checkFailed'));
            return false;
        }
    };

    const startPaymentPolling = (id: string) => {
        const interval = setInterval(async () => {
            const isCompleted = await checkPaymentStatus(id);
            if (isCompleted) {
                clearInterval(interval);
            }
        }, 3000);

        // 5分钟后停止轮询
        setTimeout(() => {
            clearInterval(interval);
            if (paymentStatus === 'pending') {
                message.warning(t('bill.payment.timeout'));
                setPaymentModalVisible(false);
            }
        }, 5 * 60 * 1000);
    };

    const handleRechargeClick = () => {
        setRechargeVisible(true);
    };

    const handleRecharge = async () => {
        try {
            const formattedAmount = Number(rechargeAmount.toFixed(2));
            const res = await fetchCustom('/api/alipay/recharge', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    amount: formattedAmount,
                    return_url: window.location.href,
                }),
            });
            if (res.ok) {
                const data = await res.json();
                setPaymentUrl(data.data.url);
                setPaymentStatus('pending');
                setPaymentModalVisible(true);
                setRechargeVisible(false);
                
                // 打开支付页面
                window.open(data.data.url, '_blank');
                
                // 开始轮询支付状态
                startPaymentPolling(data.data.id);
            } else {
                throw new Error(await res.text());
            }
        } catch (_err) {
            message.error(t('bill.payment.createFailed'));
        }
    };

    const columns: ProColumns<Bill>[] = [
        {
            title: t('bill.table.id'),
            dataIndex: 'id',
            width: '10%',
            valueType: 'text'
        },
        {
            title: t('bill.table.related_exp_id'),
            dataIndex: 'related_exp_id',
            width: '20%',
            valueType: 'text',
        },
        {
            title: t('bill.table.item'),
            dataIndex: 'item',
            width: '20%',
            valueEnum: {
                'llm_input_token': t('bill.table.llm_input_token'),
                'llm_output_token': t('bill.table.llm_output_token'),
                'run_time': t('bill.table.run_time'),
                'recharge': t('bill.table.recharge'),
            },
        },
        {
            title: t('bill.table.amount'),
            dataIndex: 'amount',
            width: '10%',
            valueType: 'money',
            render: (_, record) => record.amount,
            search: false,
        },
        {
            title: t('bill.table.unit_price'),
            dataIndex: 'unit_price',
            width: '10%',
            valueType: 'money',
            render: (_, record) => record.unit_price,
            search: false,
        },
        {
            title: t('bill.table.quantity'),
            dataIndex: 'quantity',
            width: '10%',
            search: false,
        },
        {
            title: t('bill.table.description'),
            dataIndex: 'description',
            width: '10%',
            valueType: 'text',
            search: false,
        },
        {
            title: t('bill.table.createdAt'),
            dataIndex: 'created_at',
            width: '10%',
            valueType: 'dateTime',
            search: false,
        },
    ];

    return (
        <div style={{ margin: "16px" }}>
            <Row>
                <Col span={24}>
                    <Card>
                        <Row justify="space-between" align="middle">
                            <Col>
                                <Space>
                                    <h2>{t('bill.balance')}: ￥{account?.balance ? Number(account.balance).toFixed(2) : '0.00'}</h2>
                                    <Button 
                                        type="text" 
                                        icon={<SyncOutlined />} 
                                        onClick={fetchAccount}
                                        title={t('bill.refresh')}
                                    />
                                </Space>
                            </Col>
                            <Col>
                                <Popconfirm
                                    title={t('bill.confirmRecharge.title')}
                                    description={
                                        <div>
                                            <p>{t('bill.confirmRecharge.content')}</p>
                                            <p>1. {t('bill.confirmRecharge.changeable')}</p>
                                        </div>
                                    }
                                    placement="bottomLeft"
                                    onConfirm={handleRechargeClick}
                                    okText={t('bill.confirmRecharge.okText')}
                                    cancelText={t('bill.confirmRecharge.cancelText')}
                                >
                                    <Button type="primary">
                                        {t('bill.recharge')}
                                    </Button>
                                </Popconfirm>
                            </Col>
                        </Row>
                    </Card>
                </Col>
            </Row>

            <Row style={{ marginTop: "16px" }}>
                <Col span={24}>
                    <ProTable<Bill>
                        headerTitle={t('bill.table.title')}
                        actionRef={actionRef}
                        columns={columns}
                        cardBordered
                        request={async (params) => {
                            try {
                                const queryParams = new URLSearchParams();
                                if (params.item) queryParams.append('item', params.item);
                                if (params.current) queryParams.append('skip', ((params.current - 1) * (params.pageSize || 10)).toString());
                                if (params.pageSize) queryParams.append('limit', params.pageSize.toString());

                                const res = await fetchCustom(`/api/bills?${queryParams.toString()}`);
                                const data = await res.json();
                                return {
                                    data: data.data,
                                    success: true,
                                    total: data.total,
                                };
                            } catch (err) {
                                message.error('Failed to fetch bills: ' + err);
                                return { data: [], success: false };
                            }
                        }}
                        rowKey="id"
                        search={{
                            labelWidth: 120,
                        }}
                        pagination={{
                            pageSize: 10,
                        }}
                    />
                </Col>
            </Row>

            <Modal
                title={t('bill.recharge')}
                open={rechargeVisible}
                onOk={handleRecharge}
                onCancel={() => setRechargeVisible(false)}
            >
                <Space direction="vertical" style={{ width: '100%' }}>
                    <InputNumber
                        min={0.01}
                        value={rechargeAmount}
                        onChange={(value) => setRechargeAmount(value ? Number(value.toFixed(2)) : 0)}
                        style={{ width: '100%' }}
                        addonBefore="￥"
                        precision={2}
                        step={0.01}
                    />
                    <div>
                        <Space wrap>
                            {presetAmounts.map((amount) => (
                                <Button
                                    key={amount}
                                    type={rechargeAmount === amount ? 'primary' : 'default'}
                                    onClick={() => setRechargeAmount(amount)}
                                >
                                    ￥{amount}
                                </Button>
                            ))}
                        </Space>
                    </div>
                    <div style={{ color: '#666', fontSize: '12px' }}>
                        <p>1. {t('bill.payment.alipayOnly')}</p>
                        <p>2. {t('bill.payment.refundInvoice')}</p>
                        <p>3. {t('bill.payment.billingItems')}</p>
                    </div>
                </Space>
            </Modal>

            <Modal
                title={t('bill.payment.title')}
                open={paymentModalVisible}
                onCancel={() => setPaymentModalVisible(false)}
                footer={null}
            >
                <Space direction="vertical" style={{ width: '100%' }}>
                    <p>{t('bill.payment.instruction')}</p>
                    <Button 
                        type="primary" 
                        onClick={() => window.open(paymentUrl, '_blank')}
                    >
                        {t('bill.payment.openPayment')}
                    </Button>
                    {paymentStatus === 'pending' && (
                        <p>{t('bill.payment.waiting')}</p>
                    )}
                </Space>
            </Modal>
        </div>
    );
};

export default Page;
