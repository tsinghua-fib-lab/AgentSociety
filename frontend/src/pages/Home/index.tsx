import React, { useState, useEffect } from 'react';
import { Typography, Button, Space, Col } from 'antd';
import { GithubOutlined } from '@ant-design/icons';
import { Trans, useTranslation } from 'react-i18next';

const { Text, Link } = Typography;

// 透明导航条样式
const newsBarStyle = {
    background: 'rgba(255, 255, 255, 0.2)',
    border: '1px solid rgba(255, 255, 255, 0.1)',
    padding: '8px 12px',
    borderRadius: '32px',
    backdropFilter: 'blur(4px)',
    maxWidth: '500px',
};

const HomePage = () => {
    const [stars, setStars] = useState(0);
    const { t } = useTranslation();

    useEffect(() => {
        fetch('https://api.github.com/repos/tsinghua-fib-lab/agentsociety')
            .then(res => res.json())
            .then(data => setStars(data.stargazers_count))
            .catch(() => setStars(0));
    }, []);

    return (
        <div style={{ maxWidth: '1200px', margin: '0 auto' }}>
            <Link href="https://agentsociety2.fiblab.net" target="_blank">
                <div style={newsBarStyle}>
                    <Space>
                        <Col
                            style={{
                                backgroundColor: '#F28F0D',
                                color: 'white',
                                borderRadius: '16px',
                                padding: '4px 12px',
                                marginRight: '8px',
                            }}
                        >{t('home.whatsNew')}</Col>
                        <Col style={{
                            color: 'white'
                        }}>
                            {t('home.releaseNotes')}
                        </Col>
                    </Space>
                </div>
            </Link>
            <Text
                italic={true}
                style={{
                    color: 'white',
                    fontSize: '4rem',
                    fontWeight: 500,
                }}
            >
                AgentSociety
            </Text>

            <div
                style={{
                    color: 'white',
                    fontSize: '1.3rem',
                    lineHeight: 1.8,
                    display: 'block',
                    marginBottom: '64px',
                }}
            >
                <Trans i18nKey="home.mainDescription" components={{ strong: <strong />, em: <em /> }} />
            </div>

            {/* 按钮组 */}
            <Space size="large">
                <Link href="/console">
                    <Button
                        type="default"
                        size="large"
                        style={{
                            height: '56px',
                            padding: '0 40px',
                            fontSize: '18px',
                            fontWeight: 'bold',
                            borderRadius: '32px',
                            color: 'white',
                            borderColor: 'white',
                            border: '2px solid white',
                            backgroundColor: 'rgba(255, 255, 255, 0.1)'
                        }}
                    >
                        {t('home.getStarted')}
                    </Button>
                </Link>

                <Link href="https://github.com/tsinghua-fib-lab/agentsociety" target="_blank">
                    <Button
                        icon={<GithubOutlined />}
                        size="large"
                        style={{
                            height: '56px',
                            padding: '0 32px',
                            fontSize: '16px',
                            borderRadius: '32px',
                            background: 'rgba(255, 255, 255, 0.1)',
                            borderColor: 'transparent',
                            color: 'white'
                        }}
                    >
                        {stars > 0 ? `${stars.toLocaleString()} ${t('home.stars')}` : 'GitHub'}
                    </Button>
                </Link>
            </Space>
        </div >
    );
};

export default HomePage;