import * as React from 'react';
import { Alert, Button, Checkbox, Empty, Input, Modal, Space, Tag, Typography } from 'antd';
import { useTranslation } from 'react-i18next';
import type { VSCodeAPI } from '../types';
import type { McpImportPreview, McpImportSource } from '../../../services/mcpImport';

export function McpImportDialog({ source, vscode, onClose }: {
  source: McpImportSource | null; vscode: VSCodeAPI; onClose: () => void;
}) {
  const { t } = useTranslation();
  const [text, setText] = React.useState('');
  const [preview, setPreview] = React.useState<McpImportPreview>();
  const [selected, setSelected] = React.useState<Set<string>>(() => new Set());
  const [targets, setTargets] = React.useState({ claude: false, codex: false });
  const [loading, setLoading] = React.useState(false);
  const [applying, setApplying] = React.useState(false);
  const [error, setError] = React.useState('');
  const [result, setResult] = React.useState<{ added: number; updated: number; skipped: number }>();
  const request = React.useRef(0);
  const errorText = (code: string) => t(`skillManagement.mcpImport.errors.${code}`, { defaultValue: t('skillManagement.mcpImport.errors.invalid_mcp_import') });
  const load = React.useCallback((kind: McpImportSource, content?: string) => {
    setLoading(true); setError(''); setPreview(undefined); setResult(undefined); setSelected(new Set());
    vscode.postMessage({ type: 'previewMcpImport', payload: { source: kind, text: content, requestId: ++request.current } });
  }, [vscode]);
  React.useEffect(() => {
    if (!source) { return; }
    setLoading(false); setApplying(false); setSelected(new Set());
    setText(''); setPreview(undefined); setResult(undefined); setError(''); setTargets({ claude: false, codex: false });
    const listener = (event: MessageEvent) => {
      const data = event.data;
      if (data?.payload?.requestId !== request.current) { return; }
      if (data.type === 'mcpImportPreview') {
        setPreview(data.payload); setSelected(new Set((data.payload as McpImportPreview).items.filter((item) => item.state === 'new').map((item) => item.key))); setLoading(false);
      }
      if (data.type === 'mcpImportError') { setError(errorText(data.payload.error)); setLoading(false); setApplying(false); }
      if (data.type === 'mcpImportCancelled') { setLoading(false); }
      if (data.type === 'mcpImportApplied') { setApplying(false); setResult(data.payload); }
    };
    window.addEventListener('message', listener);
    if (source !== 'paste') { load(source); }
    return () => { window.removeEventListener('message', listener); request.current++; };
  }, [source, vscode, load, t]);
  const sseSelected = targets.codex && preview?.items.some((item) => selected.has(item.key) && item.server?.transport === 'sse');
  const apply = () => {
    if (!preview) { return; }
    setApplying(true); setError('');
    vscode.postMessage({ type: 'applyMcpImport', payload: { token: preview.token, selected: [...selected], ...targets, requestId: ++request.current } });
  };
  return <Modal open={Boolean(source)} title={t('skillManagement.mcpImport.title')} width={720} onCancel={() => { if (!applying) { onClose(); } }} closable={!applying} footer={result ?
    <Button type="primary" onClick={onClose}>{t('skillManagement.mcpImport.done')}</Button> : <Space wrap>
      <Button onClick={onClose} disabled={applying}>{t('skillManagement.cancel')}</Button>
      <Button type="primary" loading={applying} disabled={!preview || !selected.size || loading || Boolean(sseSelected)} onClick={apply}>{t('skillManagement.mcpImport.apply', { count: selected.size })}</Button>
    </Space>}>
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      {result ? <Alert type="success" showIcon title={t('skillManagement.mcpImport.summary', result)} /> : <>
        <Typography.Text type="secondary">{t('skillManagement.mcpImport.hint')}</Typography.Text>
        {source === 'paste' ? <Input.TextArea disabled={applying} aria-label={t('skillManagement.mcpImport.paste')} placeholder={t('skillManagement.mcpImport.paste')} value={text} onChange={(event) => { setText(event.target.value); setPreview(undefined); setSelected(new Set()); setError(''); request.current++; setLoading(false); }} autoSize={{ minRows: 6, maxRows: 12 }} /> : null}
        <Button loading={loading} disabled={applying || (source === 'paste' && !text.trim())} onClick={() => { if (source) { load(source, text); } }}>{t('skillManagement.mcpImport.preview')}</Button>
        {preview?.items.some((item) => item.state === 'conflict') ? <Alert type="info" title={t('skillManagement.mcpImport.conflicts')} /> : null}
        {preview && !preview.items.length ? <Empty description={t('skillManagement.mcpImport.empty')} /> : null}
        {preview?.items.map((item) => <div key={item.key} style={{ border: '1px solid var(--vscode-panel-border)', borderRadius: 10, padding: 12 }}>
          <Space wrap>
            <Checkbox checked={selected.has(item.key)} disabled={applying || !['new', 'conflict'].includes(item.state)} onChange={(event) => setSelected((previous) => { const next = new Set(previous); if (event.target.checked) { next.add(item.key); } else { next.delete(item.key); } return next; })}>{item.name}</Checkbox>
            <Tag color={item.state === 'invalid' ? 'error' : item.state === 'conflict' ? 'warning' : undefined}>{t(`skillManagement.mcpImport.state_${item.state}`)}</Tag>
          </Space>
          {item.server ? <Typography.Text type="secondary" style={{ display: 'block', fontSize: 12, overflowWrap: 'anywhere' }}>{item.server.transport} · {item.server.command ?? item.server.url} · {t('skillManagement.mcpImport.fields', { args: item.server.args?.length ?? 0, env: Object.keys(item.server.env ?? {}).length, headers: Object.keys(item.server.httpHeaders ?? {}).length })}</Typography.Text> : null}
          {item.reason ? <Typography.Text type="danger" style={{ display: 'block' }}>{errorText(item.reason)}</Typography.Text> : null}
        </div>)}
        {preview?.items.length ? <>
          <Typography.Text type="secondary">{t('skillManagement.mcpImport.targets')}</Typography.Text>
          <Space wrap>
            <Checkbox checked={targets.claude} disabled={applying} onChange={(event) => setTargets((previous) => ({ ...previous, claude: event.target.checked }))}>Claude Code</Checkbox>
            <Checkbox checked={targets.codex} disabled={applying} onChange={(event) => setTargets((previous) => ({ ...previous, codex: event.target.checked }))}>Codex</Checkbox>
          </Space>
        </> : null}
      </>}
      {sseSelected ? <Alert type="warning" title={t('skillManagement.mcpSseClaudeOnly')} /> : null}
      {error ? <Alert type="error" showIcon title={error} /> : null}
    </Space>
  </Modal>;
}
