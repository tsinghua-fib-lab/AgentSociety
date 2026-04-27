import * as React from 'react';
import {
  ConfigProvider,
  Layout,
  Typography,
  Card,
  Collapse,
  Tag,
  Space,
  Divider,
  Alert,
} from 'antd';
import {
  RocketOutlined,
  SettingOutlined,
  ApiOutlined,
  RobotOutlined,
  DatabaseOutlined,
  PlayCircleOutlined,
  BookOutlined,
  BulbOutlined,
  CodeOutlined,
  CloudServerOutlined,
  QuestionCircleOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { useVscodeTheme } from '../theme';
import '../i18n';

const { Content } = Layout;
const { Title, Text, Paragraph } = Typography;
const { Panel } = Collapse;

interface HelpPageAppProps {
  vscode: {
    postMessage: (message: unknown) => void;
  };
}

interface SectionData {
  key: string;
  title: string;
  icon: React.ReactNode;
  items: {
    title: string;
    description: string;
    commands?: string[];
    tips?: string[];
  }[];
}

export const HelpPageApp: React.FC<HelpPageAppProps> = ({ vscode }) => {
  const { isDark, palette, themeConfig } = useVscodeTheme();

  const sections: SectionData[] = [
    {
      key: 'quickstart',
      title: '快速开始',
      icon: <RocketOutlined />,
      items: [
        {
          title: '1. 配置 API 密钥',
          description: '首次使用需要配置 LLM API 密钥。点击状态栏或运行命令 "AI Social Scientist: 打开配置页面"，填写必填的 API Key 和 API Base。',
          commands: ['AI Social Scientist: 打开配置页面'],
        },
        {
          title: '2. 启动后端服务',
          description: '配置完成后，点击状态栏的 "启动后端" 按钮，或运行启动命令。后端服务是运行实验和管理数据的核心。',
          commands: ['AI Social Scientist: 启动后端', 'AI Social Scientist: 后端状态菜单'],
        },
        {
          title: '3. 管理技能',
          description: '通过技能市场查看和安装 Agent 技能或 Claude 技能。技能是插件的核心功能单元。',
          commands: ['AI Social Scientist: 打开技能市场'],
        },
        {
          title: '4. 配置实验',
          description: '在环境和智能体页面选择要使用的模块，然后配置初始化参数和预填充参数。',
          commands: ['AI Social Scientist: 打开环境和智能体', 'AI Social Scientist: 打开初始化配置', 'AI Social Scientist: 打开预填充参数'],
        },
        {
          title: '5. 运行与回放',
          description: '实验运行后，可以通过回放功能查看 Agent 的行为轨迹和对话记录。',
          commands: ['AI Social Scientist: 打开回放'],
        },
      ],
    },
    {
      key: 'features',
      title: '主要功能',
      icon: <ThunderboltOutlined />,
      items: [
        {
          title: '技能管理',
          description: '管理 Agent 技能和 Claude 技能。Agent 技能用于模拟实验中的智能体行为，Claude 技能用于扩展 Claude Code 的能力。',
          tips: [
            '可以从远程仓库安装技能',
            '支持本地自定义技能开发',
            '技能可以启用/禁用/更新',
          ],
        },
        {
          title: '后端服务管理',
          description: '管理实验后端服务，包括启动、停止、重启、查看日志等操作。后端提供 REST API 接口。',
          tips: [
            '状态栏显示当前服务状态',
            '支持一键打开 API 文档',
            '可以复制服务 URL 到剪贴板',
          ],
        },
        {
          title: '实验配置',
          description: '配置实验的环境模块和 Agent 参数。支持预填充参数配置，简化实验初始化流程。',
        },
        {
          title: '模拟回放',
          description: '可视化回放实验过程，查看 Agent 的位置移动、对话记录和行为轨迹。',
        },
      ],
    },
    {
      key: 'pages',
      title: '页面说明',
      icon: <BookOutlined />,
      items: [
        {
          title: '配置页面',
          description: '配置 LLM API、Python 环境、文献检索等服务。必填项为 Default LLM 的 API Key 和 API Base。',
          commands: ['AI Social Scientist: 打开配置页面'],
        },
        {
          title: '技能市场',
          description: '浏览和管理技能。分为 Agent 技能和 Claude 技能两个标签页，支持搜索、安装、更新、启用/禁用操作。',
          commands: ['AI Social Scientist: 打开技能市场'],
        },
        {
          title: '环境和智能体',
          description: '选择实验中要使用的环境模块和 Agent 类型。支持搜索、查看描述、自定义模块测试。',
          commands: ['AI Social Scientist: 打开环境和智能体'],
        },
        {
          title: '初始化配置',
          description: '查看和编辑实验的初始化配置，包括环境模块参数和 Agent 参数。',
          commands: ['AI Social Scientist: 打开初始化配置'],
        },
        {
          title: '预填充参数',
          description: '为环境模块和 Agent 配置预填充参数，简化实验配置流程。',
          commands: ['AI Social Scientist: 打开预填充参数'],
        },
        {
          title: '回放页面',
          description: '可视化回放实验过程，支持时间轴控制、Agent 详情查看、对话记录浏览。',
          commands: ['AI Social Scientist: 打开回放'],
        },
      ],
    },
    {
      key: 'tips',
      title: '使用技巧',
      icon: <BulbOutlined />,
      items: [
        {
          title: '命令面板快捷访问',
          description: '按 Ctrl+Shift+P (Windows/Linux) 或 Cmd+Shift+P (Mac) 打开命令面板，输入 "AI Social" 或 "AgentSociety" 快速找到所有相关命令。',
        },
        {
          title: '状态栏快速操作',
          description: '点击状态栏的 AI Social Scientist 图标，可以快速访问后端服务菜单，包括启动/停止/重启/查看日志等。',
        },
        {
          title: '自定义 Python 环境',
          description: '如果需要使用特定的 Python 环境，可以在配置页面设置 Python 路径。留空则使用系统默认 Python。',
        },
        {
          title: '验证配置',
          description: '在配置页面中，每个服务配置旁边都有验证按钮，可以快速检测配置是否正确。',
        },
        {
          title: '自定义技能开发',
          description: '在 workspace/custom/ 目录下可以开发自定义技能，插件会自动扫描并加载。',
        },
      ],
    },
    {
      key: 'faq',
      title: '常见问题',
      icon: <QuestionCircleOutlined />,
      items: [
        {
          title: '后端启动失败怎么办？',
          description: '1. 检查 Python 环境是否正确安装\n2. 检查端口 8001 是否被占用\n3. 查看后端日志获取详细错误信息\n4. 确保所有依赖包已安装',
        },
        {
          title: 'API 验证失败怎么办？',
          description: '1. 检查 API Key 是否正确\n2. 检查 API Base URL 是否正确（注意不要漏掉 /v1 后缀）\n3. 检查网络连接是否正常\n4. 确认 API 服务是否支持配置的模型',
        },
        {
          title: '技能安装后不显示？',
          description: '1. 点击刷新按钮重新扫描\n2. 检查技能目录结构是否正确\n3. 查看 Skill.md 文件是否包含正确的元数据',
        },
        {
          title: '如何更新插件？',
          description: '在 VS Code 扩展面板中搜索 "AI Social Scientist"，点击更新按钮即可。',
        },
      ],
    },
  ];

  // 玻璃态样式
  const glassCardStyle = {
    borderRadius: 12,
    border: `1px solid ${palette.panelBorder}`,
    background: isDark
      ? 'rgba(37, 37, 38, 0.6)'
      : 'rgba(255, 255, 255, 0.5)',
    backdropFilter: 'blur(16px)',
    WebkitBackdropFilter: 'blur(16px)',
    boxShadow: '0 2px 10px rgba(0,0,0,0.06)',
  };

  return (
    <ConfigProvider theme={themeConfig}>
      <Layout style={{ minHeight: '100vh', background: palette.editorBackground }}>
        <Content style={{ padding: '24px', maxWidth: 1000, margin: '0 auto', width: '100%' }}>
          {/* 头部 */}
          <div
            style={{
              marginBottom: 24,
              padding: '24px 28px',
              borderRadius: 16,
              border: `1px solid ${palette.panelBorder}`,
              background: isDark
                ? 'rgba(37, 37, 38, 0.7)'
                : 'rgba(255, 255, 255, 0.65)',
              backdropFilter: 'blur(24px)',
              WebkitBackdropFilter: 'blur(24px)',
              boxShadow: isDark
                ? '0 4px 16px rgba(0,0,0,0.2)'
                : '0 4px 16px rgba(0,0,0,0.08)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  width: 48,
                  height: 48,
                  borderRadius: 14,
                  background: `linear-gradient(135deg, ${palette.linkForeground}25 0%, ${palette.linkForeground}15 100%)`,
                  color: palette.linkForeground,
                }}
              >
                <BookOutlined style={{ fontSize: 22 }} />
              </span>
              <div>
                <Title level={3} style={{ margin: 0 }}>AI Social Scientist 使用指南</Title>
                <Text type="secondary">插件功能介绍与操作说明</Text>
              </div>
            </div>
            <Paragraph style={{ margin: 0, color: palette.descriptionForeground }}>
              AI Social Scientist 是一个基于大语言模型的智能体模拟框架，支持构建复杂的城市模拟和社会实验。
              本指南将帮助您快速了解插件的核心功能和使用方法。
            </Paragraph>
          </div>

          {/* 主要内容 */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {sections.map((section) => (
              <Card
                key={section.key}
                title={
                  <Space>
                    <span style={{ color: palette.linkForeground }}>{section.icon}</span>
                    <span>{section.title}</span>
                  </Space>
                }
                style={glassCardStyle}
                styles={{ body: { padding: '16px 20px' } }}
              >
                <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                  {section.items.map((item, index) => (
                    <div
                      key={index}
                      style={{
                        padding: '12px 16px',
                        borderRadius: 8,
                        background: isDark
                          ? 'rgba(255, 255, 255, 0.04)'
                          : 'rgba(0, 0, 0, 0.02)',
                        border: `1px solid ${palette.panelBorder}40`,
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 6 }}>
                        <Text strong style={{ fontSize: 14 }}>{item.title}</Text>
                      </div>
                      <Paragraph
                        style={{
                          margin: 0,
                          color: palette.descriptionForeground,
                          fontSize: 13,
                          lineHeight: 1.6,
                          whiteSpace: 'pre-wrap',
                        }}
                      >
                        {item.description}
                      </Paragraph>
                      {item.commands && item.commands.length > 0 && (
                        <div style={{ marginTop: 10, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                          {item.commands.map((cmd, cmdIndex) => (
                            <Tag
                              key={cmdIndex}
                              style={{
                                margin: 0,
                                borderRadius: 4,
                                background: isDark
                                  ? 'rgba(22, 119, 255, 0.15)'
                                  : 'rgba(22, 119, 255, 0.08)',
                                border: `1px solid ${palette.linkForeground}30`,
                                color: palette.linkForeground,
                                fontSize: 11,
                              }}
                            >
                              {cmd}
                            </Tag>
                          ))}
                        </div>
                      )}
                      {item.tips && item.tips.length > 0 && (
                        <div style={{ marginTop: 10 }}>
                          {item.tips.map((tip, tipIndex) => (
                            <div
                              key={tipIndex}
                              style={{
                                display: 'flex',
                                alignItems: 'flex-start',
                                gap: 6,
                                marginBottom: 4,
                              }}
                            >
                              <BulbOutlined style={{ color: palette.successForeground, fontSize: 12, marginTop: 3 }} />
                              <Text style={{ fontSize: 12, color: palette.descriptionForeground }}>{tip}</Text>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </Card>
            ))}
          </div>

          {/* 底部信息 */}
          <div
            style={{
              marginTop: 24,
              padding: '16px 20px',
              borderRadius: 12,
              border: `1px solid ${palette.panelBorder}`,
              background: isDark
                ? 'rgba(37, 37, 38, 0.5)'
                : 'rgba(255, 255, 255, 0.4)',
              textAlign: 'center',
            }}
          >
            <Text type="secondary" style={{ fontSize: 12 }}>
              更多信息请访问项目文档或 GitHub 仓库
            </Text>
          </div>
        </Content>
      </Layout>
    </ConfigProvider>
  );
};
