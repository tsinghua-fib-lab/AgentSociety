import * as React from 'react';
import {
  ConfigProvider,
  Layout,
  Typography,
  Card,
  Button,
  Space,
  Spin,
  Alert,
} from 'antd';
import { BookOutlined, ExportOutlined, ReloadOutlined, FileTextOutlined } from '@ant-design/icons';
import { XMarkdown } from '@ant-design/x-markdown';
import { useVscodeTheme } from '../theme';
import '../i18n';
import type { VSCodeAPI } from './types';

const { Content } = Layout;
const { Text } = Typography;

declare global {
  interface Window {
    HELP_CONTENT?: string;
    RTD_URL?: string;
  }
}

interface HelpPageAppProps {
  vscode: VSCodeAPI;
}

type ViewMode = 'loading' | 'iframe' | 'fallback';

const HEADING_ID_RE = /[^\w\u4e00-\u9fff-]/g;

const slugify = (text: string): string =>
  text.replace(HEADING_ID_RE, '-').replace(/-+/g, '-').replace(/^-|-$/g, '');

export const HelpPageApp: React.FC<HelpPageAppProps> = ({ vscode }) => {
  const { isDark, palette, themeConfig } = useVscodeTheme();
  const [helpContent, setHelpContent] = React.useState<string>('');
  const [viewMode, setViewMode] = React.useState<ViewMode>('loading');
  const [iframeError, setIframeError] = React.useState(false);
  const iframeRef = React.useRef<HTMLIFrameElement>(null);

  // Use ref for callbacks to avoid stale closure over viewMode
  const viewModeRef = React.useRef<ViewMode>(viewMode);
  viewModeRef.current = viewMode;

  const rtdUrl = window.RTD_URL ?? 'https://agentsociety2.readthedocs.io/en/latest/';
  const locale = typeof navigator !== 'undefined' ? navigator.language : 'zh-CN';
  const isZh = locale.startsWith('zh');

  React.useEffect(() => {
    if (window.HELP_CONTENT) {
      setHelpContent(window.HELP_CONTENT);
    }
  }, []);

  // Timeout: fallback after 8 seconds if iframe hasn't loaded
  React.useEffect(() => {
    if (viewMode !== 'loading') {
      return;
    }
    const timer = setTimeout(() => {
      if (viewModeRef.current === 'loading') {
        setIframeError(true);
        setViewMode('fallback');
        // Stop the iframe from continuing to load
        if (iframeRef.current) {
          iframeRef.current.src = 'about:blank';
        }
      }
    }, 8000);
    return () => clearTimeout(timer);
  }, [viewMode]);

  const handleIframeLoad = React.useCallback(() => {
    if (viewModeRef.current !== 'loading') {
      return;
    }
    setViewMode('iframe');
    setIframeError(false);
  }, []);

  const handleIframeError = React.useCallback(() => {
    if (viewModeRef.current === 'iframe') {
      return;
    }
    setIframeError(true);
    setViewMode('fallback');
    if (iframeRef.current) {
      iframeRef.current.src = 'about:blank';
    }
  }, []);

  const handleLinkClick = (href: string) => {
    if (href.startsWith('command:')) {
      const commandId = href.substring(8);
      vscode.postMessage({
        command: 'openCommand',
        commandId,
      });
    } else if (href.startsWith('#')) {
      const element = document.getElementById(href.substring(1));
      if (element) {
        element.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    } else if (href.startsWith('http://') || href.startsWith('https://')) {
      vscode.postMessage({
        command: 'openUrl',
        url: href,
      });
    }
  };

  const markdownComponents = {
    a: ({ href, children }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => {
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
    },
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
      const id = slugify(text);
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
      const id = slugify(text);
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
      const id = slugify(text);
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

  const panelCardStyle: React.CSSProperties = {
    borderRadius: 16,
    border: `1px solid ${palette.panelBorder}`,
    background: palette.surfaceMuted,
  };

  const switchToFallback = () => {
    setViewMode('fallback');
  };

  const switchToIframe = () => {
    setViewMode('loading');
    setIframeError(false);
    if (iframeRef.current) {
      iframeRef.current.src = rtdUrl;
    }
  };

  return (
    <ConfigProvider theme={themeConfig}>
      <Layout style={{ minHeight: '100vh', background: palette.editorBackground }}>
        <Content className="as-page-content" style={{ padding: '24px', maxWidth: 1000, margin: '0 auto', width: '100%' }}>
          {/* Header Card */}
          <Card
            style={{
              ...panelCardStyle,
              marginBottom: 16,
            }}
            styles={{ body: { padding: '16px 24px' } }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <span
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    width: 44,
                    height: 44,
                    borderRadius: 12,
                    background: `color-mix(in srgb, ${palette.linkForeground} 12%, transparent)`,
                    color: palette.linkForeground,
                  }}
                >
                  <BookOutlined style={{ fontSize: 20 }} />
                </span>
                <div>
                  <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>
                    {isZh ? 'AI Social Scientist 使用指南' : 'AI Social Scientist User Guide'}
                  </h1>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {isZh ? '插件功能介绍与操作说明' : 'Plugin features and usage guide'}
                  </Text>
                </div>
              </div>
              <Space size={8}>
                {viewMode === 'iframe' && (
                  <Button
                    size="small"
                    icon={<FileTextOutlined />}
                    onClick={switchToFallback}
                  >
                    {isZh ? '离线文档' : 'Offline'}
                  </Button>
                )}
                {viewMode === 'fallback' && (
                  <Button
                    size="small"
                    icon={<ReloadOutlined />}
                    onClick={switchToIframe}
                  >
                    {isZh ? '在线文档' : 'Online'}
                  </Button>
                )}
                <Button
                  size="small"
                  onClick={() => handleLinkClick('command:aiSocialScientist.openConfigPage')}
                >
                  {isZh ? '配置' : 'Config'}
                </Button>
                <Button
                  size="small"
                  onClick={() => handleLinkClick('command:aiSocialScientist.openSkillMarketplace')}
                >
                  {isZh ? '技能市场' : 'Skills'}
                </Button>
              </Space>
            </div>
          </Card>

          {/* iframe loading state */}
          {viewMode === 'loading' && (
            <div style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              height: 400,
              gap: 16,
            }}>
              <Spin size="large" />
              <Text type="secondary">
                {isZh ? '正在加载在线文档...' : 'Loading online documentation...'}
              </Text>
            </div>
          )}

          {/* iframe container */}
          {(viewMode === 'loading' || viewMode === 'iframe') && (
            <div style={{
              display: viewMode === 'iframe' ? 'block' : 'none',
              height: viewMode === 'iframe' ? 'calc(100vh - 180px)' : 0,
              borderRadius: 12,
              overflow: 'hidden',
              border: `1px solid ${palette.panelBorder}`,
            }}>
              <iframe
                ref={iframeRef}
                src={rtdUrl}
                onLoad={handleIframeLoad}
                onError={handleIframeError}
                style={{
                  width: '100%',
                  height: '100%',
                  border: 'none',
                  background: isDark ? '#1a1a2e' : '#ffffff',
                }}
                title={isZh ? 'AgentSociety 在线文档' : 'AgentSociety Documentation'}
                sandbox="allow-same-origin allow-scripts allow-popups allow-forms allow-top-navigation-by-user-activation"
              />
            </div>
          )}

          {/* iframe error notice */}
          {iframeError && viewMode === 'fallback' && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 16, borderRadius: 12 }}
              message={isZh ? '在线文档加载失败' : 'Failed to load online documentation'}
              description={
                <span>
                  {isZh
                    ? '无法连接到 ReadTheDocs，已切换到本地文档。'
                    : 'Cannot connect to ReadTheDocs, switched to offline documentation.'}
                  {' '}
                  <a
                    onClick={(e) => { e.preventDefault(); handleLinkClick(rtdUrl); }}
                    style={{ color: palette.linkForeground, cursor: 'pointer' }}
                  >
                    {isZh ? '在浏览器中打开在线文档' : 'Open online docs in browser'}
                    <ExportOutlined style={{ marginLeft: 4, fontSize: 12 }} />
                  </a>
                </span>
              }
            />
          )}

          {/* Fallback Markdown content */}
          {viewMode === 'fallback' && (
            <Card
              style={panelCardStyle}
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
          )}

          {/* Footer */}
          <div
            style={{
              marginTop: 16,
              padding: '12px 20px',
              borderRadius: 12,
              border: `1px solid ${palette.panelBorder}`,
              background: isDark
                ? 'rgba(37, 37, 38, 0.5)'
                : 'rgba(255, 255, 255, 0.4)',
              textAlign: 'center',
            }}
          >
            <Text type="secondary" style={{ fontSize: 12 }}>
              {isZh ? '更多信息请访问 ' : 'For more info, visit '}
              <a
                onClick={(e) => {
                  e.preventDefault();
                  handleLinkClick('https://agentsociety2.readthedocs.io/');
                }}
                style={{ color: palette.linkForeground, cursor: 'pointer' }}
              >
                ReadTheDocs
              </a>
              {' | '}
              <a
                onClick={(e) => {
                  e.preventDefault();
                  handleLinkClick('https://github.com/tsinghua-fib-lab/agentsociety');
                }}
                style={{ color: palette.linkForeground, cursor: 'pointer' }}
              >
                GitHub
              </a>
              {' | '}
              <a
                onClick={(e) => {
                  e.preventDefault();
                  handleLinkClick('https://github.com/tsinghua-fib-lab/agentsociety/issues');
                }}
                style={{ color: palette.linkForeground, cursor: 'pointer' }}
              >
                {isZh ? '问题反馈' : 'Issues'}
              </a>
            </Text>
          </div>
        </Content>
      </Layout>
    </ConfigProvider>
  );
};
