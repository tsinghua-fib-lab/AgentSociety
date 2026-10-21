/**
 * JSON 查看器组件
 *
 * 支持：
 * - 语法高亮（使用 @ant-design/x CodeHighlighter）
 * - 树形折叠展开
 * - 复制功能
 * - 深色/浅色主题
 * - 键值对高亮搜索
 */

import * as React from 'react';
import { Typography, Tooltip, Space, Button, Input, Empty } from 'antd';
import { CopyOutlined, ExpandOutlined, CompressOutlined, SearchOutlined } from '@ant-design/icons';
import { CodeHighlighter } from '@ant-design/x';
import { useVscodeTheme } from '../theme';

const { Text } = Typography;

interface JsonViewerProps {
  /** JSON 数据对象 */
  data: Record<string, any> | any[] | null | undefined;
  /** 或者直接传入 JSON 字符串 */
  jsonString?: string;
  /** 是否显示复制按钮 */
  showCopy?: boolean;
  /** 是否显示展开/折叠按钮 */
  showExpandCollapse?: boolean;
  /** 是否显示搜索框 */
  showSearch?: boolean;
  /** 初始展开层级，默认 2 */
  defaultExpandDepth?: number;
  /** 最大高度，超出滚动 */
  maxHeight?: string;
  /** 是否暗色主题 */
  isDark?: boolean;
  /** 标题 */
  title?: string;
  /** 空数据时的提示 */
  emptyText?: string;
}

interface JsonNodeProps {
  keyName?: string;
  value: any;
  depth: number;
  expandDepth: number;
  searchTerm?: string;
  isDark: boolean;
}

/**
 * JSON 节点渲染组件（支持折叠）
 */
const JsonNode: React.FC<JsonNodeProps> = ({
  keyName,
  value,
  depth,
  expandDepth,
  searchTerm,
  isDark,
}) => {
  const [expanded, setExpanded] = React.useState(depth < expandDepth);
  const isExpandable = typeof value === 'object' && value !== null;
  const isArray = Array.isArray(value);

  const normalizedSearchTerm = searchTerm?.toLowerCase();
  const isMatch = Boolean(
    normalizedSearchTerm &&
      (String(keyName ?? '').toLowerCase().includes(normalizedSearchTerm) ||
        String(value).toLowerCase().includes(normalizedSearchTerm))
  );
  const matchStyle = isMatch
    ? { backgroundColor: 'var(--vscode-editor-findMatchHighlightBackground, #ea5c0055)' }
    : undefined;

  // 渲染值
  const renderValue = () => {
    if (value === null) {
      return <Text type="secondary">null</Text>;
    }
    if (value === undefined) {
      return <Text type="secondary">undefined</Text>;
    }
    if (typeof value === 'boolean') {
      return <Text style={{ color: 'var(--vscode-terminal-ansiYellow, #d4380d)' }}>{String(value)}</Text>;
    }
    if (typeof value === 'number') {
      return <Text style={{ color: 'var(--vscode-terminal-ansiBlue, #096dd9)' }}>{value}</Text>;
    }
    if (typeof value === 'string') {
      return <Text style={{ color: 'var(--vscode-terminal-ansiGreen, #389e0d)' }}>"{value}"</Text>;
    }
    return null;
  };

  // 原始值渲染（非对象）
  if (!isExpandable) {
    return (
      <div style={{ display: 'flex', alignItems: 'baseline', gap: '4px', paddingLeft: keyName ? '0' : '16px', ...matchStyle }}>
        {keyName !== undefined && (
          <>
            <Text strong style={{ color: 'var(--vscode-terminal-ansiMagenta, #722ed1)' }}>"{keyName}"</Text>
            <Text type="secondary">:</Text>
          </>
        )}
        {renderValue()}
      </div>
    );
  }

  // 对象/数组渲染
  const entries = isArray ? value.map((v: any, i: number) => [i, v]) : Object.entries(value);
  const bracketOpen = isArray ? '[' : '{';
  const bracketClose = isArray ? ']' : '}';

  if (entries.length === 0) {
    return (
      <div style={{ display: 'flex', alignItems: 'baseline', gap: '4px' }}>
        {keyName !== undefined && (
          <>
            <Text strong style={{ color: 'var(--vscode-terminal-ansiMagenta, #722ed1)' }}>"{keyName}"</Text>
            <Text type="secondary">:</Text>
          </>
        )}
        <Text type="secondary">{bracketOpen}</Text>
        <Text type="secondary" style={{ marginLeft: '8px' }}>{bracketClose}</Text>
      </div>
    );
  }

  return (
    <div style={{ paddingLeft: keyName ? '0' : '0' }}>
      <div
        style={{ display: 'flex', alignItems: 'center', gap: '4px', cursor: 'pointer', ...matchStyle }}
        onClick={() => setExpanded(!expanded)}
      >
        {keyName !== undefined && (
          <>
            <Text strong style={{ color: 'var(--vscode-terminal-ansiMagenta, #722ed1)' }}>"{keyName}"</Text>
            <Text type="secondary">:</Text>
          </>
        )}
        <Text type="secondary" style={{ fontSize: '10px', marginLeft: '4px' }}>
          {expanded ? '▼' : '▶'}
        </Text>
        <Text type="secondary">{bracketOpen}</Text>
        {!expanded && (
          <>
            <Text type="secondary" style={{ fontSize: '12px' }}>
              {entries.length} {isArray ? 'items' : 'keys'}
            </Text>
            <Text type="secondary">{bracketClose}</Text>
          </>
        )}
      </div>
      {expanded && (
        <div
          style={{
            paddingLeft: '16px',
            borderLeft: '1px solid var(--vscode-panel-border, #d9d9d9)',
            marginLeft: '8px',
          }}
        >
          {entries.map(([k, v]) => (
            <JsonNode
              key={String(k)}
              keyName={isArray ? undefined : String(k)}
              value={v}
              depth={depth + 1}
              expandDepth={expandDepth}
              searchTerm={searchTerm}
              isDark={isDark}
            />
          ))}
          <Text type="secondary">{bracketClose}</Text>
        </div>
      )}
    </div>
  );
};

/**
 * JSON 查看器组件
 */
export const JsonViewer: React.FC<JsonViewerProps> = ({
  data,
  jsonString,
  showCopy = true,
  showExpandCollapse = true,
  showSearch = false,
  defaultExpandDepth = 2,
  maxHeight,
  isDark,
  title,
  emptyText = 'No data',
}) => {
  const [expandDepth, setExpandDepth] = React.useState(defaultExpandDepth);
  const [searchTerm, setSearchTerm] = React.useState('');
  const [copied, setCopied] = React.useState(false);
  const { isDark: themeIsDark } = useVscodeTheme();

  // 检测暗色主题
  const darkMode = isDark ?? themeIsDark;

  // 解析数据
  const jsonData = React.useMemo(() => {
    if (data !== undefined && data !== null) return data;
    if (jsonString) {
      try {
        return JSON.parse(jsonString);
      } catch {
        return null;
      }
    }
    return null;
  }, [data, jsonString]);

  // JSON 字符串
  const jsonStr = React.useMemo(() => {
    return JSON.stringify(jsonData, null, 2);
  }, [jsonData]);

  // 复制功能
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(jsonStr);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  // 全部展开
  const handleExpandAll = () => setExpandDepth(Infinity);

  // 全部折叠
  const handleCollapseAll = () => setExpandDepth(0);

  // 空数据
  if (!jsonData) {
    return <Empty description={emptyText} />;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
      {/* 工具栏 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Space>
          {title && <Text strong>{title}</Text>}
        </Space>
        <Space size="small">
          {showSearch && (
            <Input
              placeholder="Search..."
              prefix={<SearchOutlined />}
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              size="small"
              style={{ width: '150px' }}
              allowClear
            />
          )}
          {showExpandCollapse && (
            <>
              <Tooltip title="Expand all">
                <Button
                  size="small"
                  icon={<ExpandOutlined />}
                  onClick={handleExpandAll}
                />
              </Tooltip>
              <Tooltip title="Collapse all">
                <Button
                  size="small"
                  icon={<CompressOutlined />}
                  onClick={handleCollapseAll}
                />
              </Tooltip>
            </>
          )}
          {showCopy && (
            <Tooltip title={copied ? 'Copied!' : 'Copy JSON'}>
              <Button
                size="small"
                icon={<CopyOutlined />}
                onClick={handleCopy}
                type={copied ? 'primary' : 'default'}
              />
            </Tooltip>
          )}
        </Space>
      </div>

      {/* JSON 内容 */}
      <div
        style={{
          maxHeight: maxHeight,
          overflow: 'auto',
          padding: '12px',
          backgroundColor: 'var(--vscode-textCodeBlock-background, #f5f5f5)',
          borderRadius: '4px',
          fontFamily: 'var(--vscode-editor-font-family, Consolas, Monaco, "Courier New", monospace)',
          fontSize: '13px',
        }}
      >
        <JsonNode
          value={jsonData}
          depth={0}
          expandDepth={expandDepth}
          searchTerm={searchTerm}
          isDark={darkMode}
        />
      </div>
    </div>
  );
};

/**
 * 简单的 JSON 高亮显示（使用 CodeHighlighter）
 * 适用于小量 JSON 数据的快速展示
 */
export const JsonHighlight: React.FC<{
  data: Record<string, any> | any[] | null | undefined;
  isDark?: boolean;
  maxHeight?: string;
}> = ({ data, maxHeight = '300px' }) => {

  if (!data) return <Empty description="No data" />;

  const jsonStr = JSON.stringify(data, null, 2);

  return (
    <div style={{ maxHeight, overflow: 'auto' }}>
      <CodeHighlighter
        lang="json"
        style={{
          margin: 0,
          background: 'var(--vscode-textCodeBlock-background, #f5f5f5)',
        }}
      >
        {jsonStr}
      </CodeHighlighter>
    </div>
  );
};

export default JsonViewer;
