import * as React from 'react';
import {
  ConfigProvider,
  Layout,
  Typography,
  Card,
  Button,
  Space,
  message,
} from 'antd';
import { BookOutlined, ExportOutlined } from '@ant-design/icons';
import { XMarkdown } from '@ant-design/x-markdown';
import { useVscodeTheme } from '../theme';
import '../i18n';
import type { VSCodeAPI } from './types';

const { Content } = Layout;
const { Text } = Typography;

declare global {
  interface Window {
    HELP_CONTENT?: string;
  }
}

interface HelpPageAppProps {
  vscode: VSCodeAPI;
}

export const HelpPageApp: React.FC<HelpPageAppProps> = ({ vscode }) => {
  const { isDark, palette, themeConfig } = useVscodeTheme();
  const [helpContent, setHelpContent] = React.useState<string>('');

  React.useEffect(() => {
    // 从 window.HELP_CONTENT 获取内容
    if (window.HELP_CONTENT) {
      setHelpContent(window.HELP_CONTENT);
    }
  }, []);

  // 处理链接点击
  const handleLinkClick = (href: string) => {
    if (href.startsWith('command:')) {
      // 命令链接
      const commandId = href.substring(8);
      vscode.postMessage({
        command: 'openCommand',
        commandId,
      });
    } else if (href.startsWith('#')) {
      // 锚点链接 - 滚动到对应位置
      const element = document.getElementById(href.substring(1));
      if (element) {
        element.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    } else if (href.startsWith('http://') || href.startsWith('https://')) {
      // 外部URL
      vscode.postMessage({
        command: 'openUrl',
        url: href,
      });
    }
  };

  // 自定义 Markdown 组件
  const markdownComponents = {
    a: ({ href, children }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
      (() => {
        const isCommand = Boolean(href && href.startsWith('command:'));
        const isExternal = Boolean(href && (href.startsWith('http://') || href.startsWith('https://')));
        const baseStyle: React.CSSProperties = {
          color: palette.linkForeground,
          cursor: 'pointer',
          textDecoration: 'none',
        };
        const commandStyle: React.CSSProperties = isCommand
          ? {
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            padding: '3px 10px',
            borderRadius: 999,
            border: `1px solid ${palette.panelBorder}`,
            background: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.04)',
            lineHeight: 1.6,
            userSelect: 'none',
            whiteSpace: 'nowrap',
          }
          : {};
        return (
          <a
            href={href}
            tabIndex={0}
            role="link"
            onClick={(e) => {
              e.preventDefault();
              if (href) {
                handleLinkClick(href);
              }
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                if (href) {
                  handleLinkClick(href);
                }
              }
            }}
            style={{
              ...baseStyle,
              ...commandStyle,
            }}
          >
            {children}
            {isExternal && (
              <ExportOutlined style={{ marginLeft: 4, fontSize: 12 }} />
            )}
          </a>
        );
      })()
    ),
    table: ({ children }: React.HTMLAttributes<HTMLTableElement>) => (
      <div style={{ overflowX: 'auto', margin: '16px 0' }}>
        <table
          style={{
            width: '100%',
            borderCollapse: 'collapse',
            fontSize: 13,
          }}
        >
          {children}
        </table>
      </div>
    ),
    th: ({ children }: React.ThHTMLAttributes<HTMLTableCellElement>) => (
      <th
        style={{
          padding: '12px 16px',
          textAlign: 'left',
          borderBottom: `2px solid ${palette.panelBorder}`,
          background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.02)',
          fontWeight: 600,
        }}
      >
        {children}
      </th>
    ),
    td: ({ children }: React.TdHTMLAttributes<HTMLTableCellElement>) => (
      <td
        style={{
          padding: '10px 16px',
          borderBottom: `1px solid ${palette.panelBorder}60`,
        }}
      >
        {children}
      </td>
    ),
    h1: ({ children }: React.HTMLAttributes<HTMLHeadingElement>) => {
      const text = typeof children === 'string' ? children : '';
      const id = text.replace(/\s+/g, '-');
      return (
        <h1
          id={id || undefined}
          style={{
            fontSize: 28,
            fontWeight: 700,
            marginBottom: 24,
            paddingBottom: 16,
            borderBottom: `1px solid ${palette.panelBorder}`,
          }}
        >
          {children}
        </h1>
      );
    },
    h2: ({ children }: React.HTMLAttributes<HTMLHeadingElement>) => {
      const text = typeof children === 'string' ? children : '';
      const id = text.replace(/\s+/g, '-');
      return (
        <h2
          id={id || undefined}
          style={{
            fontSize: 22,
            fontWeight: 600,
            marginTop: 32,
            marginBottom: 16,
            paddingBottom: 8,
            borderBottom: `1px solid ${palette.panelBorder}60`,
          }}
        >
          {children}
        </h2>
      );
    },
    h3: ({ children }: React.HTMLAttributes<HTMLHeadingElement>) => {
      const text = typeof children === 'string' ? children : '';
      const id = text.replace(/\s+/g, '-');
      return (
        <h3
          id={id || undefined}
          style={{
            fontSize: 18,
            fontWeight: 600,
            marginTop: 24,
            marginBottom: 12,
          }}
        >
          {children}
        </h3>
      );
    },
    p: ({ children }: React.HTMLAttributes<HTMLParagraphElement>) => (
      <p style={{ marginBottom: 16, lineHeight: 1.7 }}>{children}</p>
    ),
    ul: ({ children }: React.HTMLAttributes<HTMLUListElement>) => (
      <ul style={{ marginBottom: 16, paddingLeft: 24, lineHeight: 1.8 }}>{children}</ul>
    ),
    ol: ({ children }: React.OlHTMLAttributes<HTMLOListElement>) => (
      <ol style={{ marginBottom: 16, paddingLeft: 24, lineHeight: 1.8 }}>{children}</ol>
    ),
    li: ({ children }: React.LiHTMLAttributes<HTMLLIElement>) => (
      <li style={{ marginBottom: 6 }}>{children}</li>
    ),
    blockquote: ({ children }: React.BlockquoteHTMLAttributes<HTMLQuoteElement>) => (
      <blockquote
        style={{
          margin: '16px 0',
          padding: '12px 16px',
          borderLeft: `4px solid ${palette.linkForeground}`,
          background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.02)',
          borderRadius: '0 8px 8px 0',
        }}
      >
        {children}
      </blockquote>
    ),
    code: ({ children, className }: React.HTMLAttributes<HTMLElement>) => {
      const isInline = !className;
      if (isInline) {
        return (
          <code
            style={{
              padding: '2px 6px',
              background: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.06)',
              borderRadius: 4,
              fontSize: 13,
              fontFamily: 'var(--vscode-editor-font-family, monospace)',
            }}
          >
            {children}
          </code>
        );
      }
      return (
        <code style={{ display: 'block', fontSize: 13 }}>{children}</code>
      );
    },
    hr: () => (
      <hr
        style={{
          border: 'none',
          borderTop: `1px solid ${palette.panelBorder}`,
          margin: '32px 0',
        }}
      />
    ),
  };

  // 玻璃态样式
  const glassCardStyle = {
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
  };

  return (
    <ConfigProvider theme={themeConfig}>
      <Layout style={{ minHeight: '100vh', background: palette.editorBackground }}>
        <Content style={{ padding: '24px', maxWidth: 1000, margin: '0 auto', width: '100%' }}>
          {/* 头部卡片 */}
          <Card
            style={{
              ...glassCardStyle,
              marginBottom: 24,
            }}
            styles={{ body: { padding: '24px 28px' } }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
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
                <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700 }}>AI Social Scientist 使用指南</h1>
                <Text type="secondary">插件功能介绍与操作说明</Text>
              </div>
            </div>
            <Space>
              <Button
                type="primary"
                onClick={() => handleLinkClick('command:aiSocialScientist.openConfigPage')}
              >
                打开配置页面
              </Button>
              <Button
                onClick={() => handleLinkClick('command:aiSocialScientist.openSkillMarketplace')}
              >
                技能市场
              </Button>
              <Button
                onClick={() => handleLinkClick('command:aiSocialScientist.backendStatusMenu')}
              >
                后端状态
              </Button>
            </Space>
          </Card>

          {/* Markdown 内容 */}
          <Card
            style={glassCardStyle}
            styles={{ body: { padding: '24px 32px' } }}
          >
            <XMarkdown
              components={markdownComponents}
              style={{
                color: palette.editorForeground,
                fontSize: 14,
                lineHeight: 1.7,
              }}
            >
              {helpContent}
            </XMarkdown>
          </Card>

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
              更多信息请访问{' '}
              <a
                onClick={(e) => {
                  e.preventDefault();
                  handleLinkClick('https://github.com/tsinghua-fib-lab/agentsociety');
                }}
                style={{ color: palette.linkForeground, cursor: 'pointer' }}
              >
                项目文档
              </a>
              {' '}或{' '}
              <a
                onClick={(e) => {
                  e.preventDefault();
                  handleLinkClick('https://github.com/tsinghua-fib-lab/agentsociety/issues');
                }}
                style={{ color: palette.linkForeground, cursor: 'pointer' }}
              >
                问题反馈
              </a>
            </Text>
          </div>
        </Content>
      </Layout>
    </ConfigProvider>
  );
};
