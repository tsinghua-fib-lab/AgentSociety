import * as React from 'react';
import { Alert, Button, Collapse, Empty, Input, Modal, Select, Space, Spin, Tag, Typography } from 'antd';
import { useTranslation } from 'react-i18next';
import type { VSCodeAPI } from '../types';
import type { McpServerRecord } from '../../../services/mcpClient';
import { DEFAULT_MCP_REGISTRY, registryFields, registryVariants, resolveRegistryServer, type RegistryServer, type RegistryPage } from '../../../shared/mcpRegistry';

export function McpRegistryBrowser({ open, vscode, onCancel, onSelect }: {
  open: boolean; vscode: VSCodeAPI; onCancel: () => void;
  onSelect: (server: Omit<McpServerRecord, 'id'>) => void;
}) {
  const { t } = useTranslation();
  const [source, setSource] = React.useState(DEFAULT_MCP_REGISTRY);
  const [search, setSearch] = React.useState('');
  const [page, setPage] = React.useState<RegistryPage>({ servers: [] });
  const [history, setHistory] = React.useState<string[]>(['']);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState('');
  const [selected, setSelected] = React.useState<RegistryServer>();
  const [variantKey, setVariantKey] = React.useState('');
  const [values, setValues] = React.useState<Record<string, string>>({});
  const sequence = React.useRef(0);
  const request = React.useRef(0);
  const load = React.useCallback((url: string, query: string, cursor = '') => {
    request.current = ++sequence.current;
    setLoading(true); setError('');
    vscode.postMessage({ type: 'listMcpRegistry', payload: { source: url, search: query, cursor, requestId: request.current } });
  }, [vscode]);

  React.useEffect(() => {
    if (!open) { return; }
    const listener = (event: MessageEvent) => {
      const data = event.data;
      if (data?.type === 'mcpRegistrySource') {
        const url = data.payload.source as string; setSource(url); setSearch(''); setHistory(['']); setSelected(undefined); load(url, '');
      }
      if (data?.payload?.requestId !== request.current) { return; }
      if (data.type === 'mcpRegistryPage') { setPage(data.payload); setLoading(false); }
      if (data.type === 'mcpRegistryError') { setError(t('skillManagement.registry.queryFailed', { code: data.payload.error })); setLoading(false); }
    };
    window.addEventListener('message', listener);
    vscode.postMessage({ type: 'getMcpRegistrySource' });
    return () => { window.removeEventListener('message', listener); request.current = ++sequence.current; };
  }, [open, vscode, load, t]);

  const variants = selected ? registryVariants(selected) : [];
  const variant = variants.find((entry) => entry.key === variantKey);
  const fields = variant ? registryFields(variant) : [];
  let resolved: Omit<McpServerRecord, 'id'> | undefined, resolveError = '';
  if (selected && variant) {
    try { resolved = resolveRegistryServer(selected, variant, values); }
    catch (failure) { resolveError = failure instanceof Error ? failure.message : ''; }
  }
  const secrets = fields.filter((field) => field.isSecret).flatMap((field) => { const value = values[field.key] ?? field.default ?? ''; return value ? [value, encodeURI(value), encodeURIComponent(value)] : []; });
  const preview = resolved ? JSON.stringify({ ...resolved,
    env: resolved.env ? Object.fromEntries(Object.keys(resolved.env).map((key) => [key, '••••'])) : undefined,
    httpHeaders: resolved.httpHeaders ? Object.fromEntries(Object.keys(resolved.httpHeaders).map((key) => [key, '••••'])) : undefined,
  }, (_key, value: unknown) => typeof value === 'string' ? secrets.reduce((text, secret) => text.split(secret).join('••••'), value) : value, 2) : '';
  const changeFilters = () => { request.current = ++sequence.current; setPage({ servers: [] }); setHistory(['']); setLoading(false); setError(''); };
  const choose = (server: RegistryServer) => {
    setSelected(server); setVariantKey(registryVariants(server)[0]?.key ?? ''); setValues({});
  };

  return <Modal open={open} title={t('skillManagement.registry.title')} width={780} onCancel={onCancel} footer={selected ? <Space wrap>
    <Button onClick={() => setSelected(undefined)}>{t('skillManagement.registry.back')}</Button>
    <Button type="primary" disabled={!resolved} onClick={() => { if (resolved) { onSelect(resolved); } }}>{t('skillManagement.registry.configure')}</Button>
  </Space> : null}>
    {selected ? <Space direction="vertical" style={{ width: '100%' }} size={12}>
      <Typography.Text strong>{selected.title ?? selected.name}</Typography.Text>
      <Typography.Text type="secondary">{selected.name} · {selected.version}</Typography.Text>
      <Typography.Paragraph>{selected.description}</Typography.Paragraph>
      {(() => { const url = selected.repository?.url ?? selected.websiteUrl; return url && /^https?:\/\//.test(url) ? <Button type="link" style={{ padding: 0 }} onClick={() => vscode.postMessage({ type: 'openExternal', payload: { url } })}>{t('skillManagement.registry.repository')}</Button> : null; })()}
      {variants.length ? <Select aria-label={t('skillManagement.registry.variant')} value={variantKey} style={{ width: '100%' }} options={variants.map((item) => ({ value: item.key, label: item.label }))} onChange={(key) => { setVariantKey(key); setValues({}); }} /> : <Alert type="info" title={t('skillManagement.registry.unsupported')} />}
      {fields.map((field) => <div key={field.key}>
        <Typography.Text>{field.label}{field.isRequired ? ' *' : ''}</Typography.Text>
        {field.description ? <Typography.Text type="secondary" style={{ display: 'block', fontSize: 12 }}>{field.description}</Typography.Text> : null}
        {field.choices?.length ? <Select aria-label={field.label} value={values[field.key] ?? field.default} options={field.choices.map((value) => ({ value, label: value }))} onChange={(value) => setValues((previous) => ({ ...previous, [field.key]: value }))} style={{ width: '100%' }} /> : field.isSecret ?
          <Input.Password aria-label={field.label} value={values[field.key] ?? field.default ?? ''} autoComplete="off" placeholder={field.placeholder} onChange={(event) => setValues((previous) => ({ ...previous, [field.key]: event.target.value }))} /> :
          <Input aria-label={field.label} value={values[field.key] ?? field.default ?? ''} placeholder={field.isRepeated ? '["value1", "value2"]' : field.placeholder} onChange={(event) => setValues((previous) => ({ ...previous, [field.key]: event.target.value }))} />}
      </div>)}
      {resolveError ? <Typography.Text type="secondary">{t(`skillManagement.registry.errors.${resolveError.split(':')[0]}`, { field: resolveError.slice(resolveError.indexOf(':') + 1), defaultValue: t('skillManagement.registry.errors.invalid') })}</Typography.Text> : null}
      {resolved ? <Collapse items={[{ key: 'preview', label: t('skillManagement.registry.preview'), children: <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', fontSize: 12 }}>{preview}</pre> }]} /> : null}
      <Typography.Text type="secondary">{t('skillManagement.registry.configureHint')}</Typography.Text>
    </Space> : <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Typography.Text type="secondary">{t('skillManagement.registry.sourceHint')}</Typography.Text>
      <Input aria-label={t('skillManagement.registry.source')} value={source} onChange={(event) => { setSource(event.target.value); changeFilters(); }} />
      <Input.Search aria-label={t('skillManagement.registry.search')} placeholder={t('skillManagement.registry.search')} value={search} onChange={(event) => { setSearch(event.target.value); changeFilters(); }} loading={loading} enterButton onSearch={() => { setHistory(['']); load(source, search); }} />
      {error ? <Alert type="error" title={error} action={<Button onClick={() => load(source, search, history[history.length - 1])}>{t('skillManagement.refresh')}</Button>} /> : null}
      {loading ? <div style={{ padding: 32, textAlign: 'center' }}><Spin /></div> : !page.servers.length ? <Empty description={t('skillManagement.registry.empty')} /> : page.servers.map((server) => <div key={`${server.name}@${server.version}`} style={{ padding: 12, border: '1px solid var(--vscode-panel-border)', borderRadius: 12 }}>
        <Space wrap style={{ display: 'flex', justifyContent: 'space-between' }}>
          <Typography.Text strong>{server.title ?? server.name}</Typography.Text><Tag>{server.version}</Tag>
        </Space>
        <Typography.Text type="secondary" style={{ display: 'block', overflowWrap: 'anywhere', fontSize: 12 }}>{server.name}</Typography.Text>
        <Typography.Paragraph ellipsis={{ rows: 2 }} style={{ margin: '6px 0' }}>{server.description}</Typography.Paragraph>
        <Button size="small" onClick={() => choose(server)}>{t('skillManagement.registry.inspect')}</Button>
      </div>)}
      <Space wrap>
        <Button disabled={loading || history.length <= 1} onClick={() => { const next = history.slice(0, -1); setHistory(next); load(source, search, next[next.length - 1]); }}>{t('skillManagement.registry.previous')}</Button>
        <Typography.Text>{history.length}</Typography.Text>
        <Button disabled={loading || !page.nextCursor} onClick={() => { const cursor = page.nextCursor!; setHistory([...history, cursor]); load(source, search, cursor); }}>{t('skillManagement.registry.next')}</Button>
      </Space>
    </Space>}
  </Modal>;
}
