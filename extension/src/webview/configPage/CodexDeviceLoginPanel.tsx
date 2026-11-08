import * as React from 'react';
import { Alert, Button, Collapse, Input, Modal, Space, Spin, Tag, Typography } from 'antd';
import { CheckCircleOutlined, CopyOutlined, LinkOutlined, LoginOutlined, ReloadOutlined, UserOutlined } from '@ant-design/icons';
import type { TFunction } from 'i18next';
import type { VSCodeAPI } from './types';
import type { CodexDeviceLoginState } from '../../services/codexDeviceLogin';

type LoginContext = {
  state: CodexDeviceLoginState;
  pending: boolean;
  authenticated: boolean;
  usingAccount: boolean;
  applying: boolean;
  onRefresh: () => void;
  openLogin: () => void;
  useAccount: () => void;
  toolTab: 'claude' | 'codex';
  selectToolTab: (tab: 'claude' | 'codex') => void;
  networkRequested: boolean;
  completeNetworkRequest: () => void;
};

const LoginContext = React.createContext<LoginContext | null>(null);

export function useCodexDeviceLogin(): LoginContext {
  const context = React.useContext(LoginContext);
  if (!context) { throw new Error('CodexDeviceLoginProvider is required'); }
  return context;
}

/** Keep an in-flight login mounted while configuration loading changes the settings layout. */
export function CodexDeviceLoginProvider({ t, vscode, loggedIn, usingAccount, onUseAccount, applying, onRefresh, onOpenSettings, children }: React.PropsWithChildren<{
  t: TFunction;
  vscode: VSCodeAPI;
  loggedIn: boolean;
  usingAccount: boolean;
  onUseAccount: () => void;
  applying: boolean;
  onRefresh: () => void;
  onOpenSettings: () => void;
}>) {
  const [state, setState] = React.useState<CodexDeviceLoginState>({ status: 'idle' });
  const [open, setOpen] = React.useState(false);
  const [toolTab, setToolTab] = React.useState<'claude' | 'codex'>('claude');
  const [networkRequested, setNetworkRequested] = React.useState(false);
  const completeNetworkRequest = React.useCallback(() => setNetworkRequested(false), []);
  const openNetworkOnClose = React.useRef(false);
  const [copied, setCopied] = React.useState<'code' | 'url' | null>(null);
  const [actionError, setActionError] = React.useState<'copy' | 'open' | null>(null);
  const pending = state.status === 'starting' || state.status === 'waiting';
  const authenticated = loggedIn || state.status === 'success';
  React.useEffect(() => {
    const receive = (event: MessageEvent) => {
      if (event.data?.command === 'codexDeviceLoginState') {
        setState(event.data.state);
        setCopied(null);
        setActionError(null);
      } else if (event.data?.command === 'codexDeviceLoginCopied') {
        setCopied(event.data.target === 'url' ? 'url' : 'code');
      } else if (event.data?.command === 'codexDeviceLoginActionError') {
        setActionError(event.data.action === 'open' ? 'open' : 'copy');
      }
    };
    window.addEventListener('message', receive);
    vscode.postMessage({ command: 'codexDeviceLogin', action: 'status' });
    return () => window.removeEventListener('message', receive);
  }, [vscode]);
  const send = (action: string) => {
    setActionError(null);
    if (action === 'start') { setState({ status: 'starting', phase: 'initializing' }); }
    vscode.postMessage({ command: 'codexDeviceLogin', action });
  };
  const close = () => {
    if (pending) { send('cancel'); }
    setOpen(false);
  };
  const useAccount = () => { onUseAccount(); setOpen(false); };
  const networkError = ['requestRejected', 'networkError', 'tlsError', 'timeout', 'serviceUnavailable'].includes(state.error ?? '');
  const errorKey = state.error ?? 'startFailed';
  const openLogin = () => {
    onOpenSettings(); setOpen(true);
    if (!pending) { send('start'); }
  };
  const selectToolTab = (tab: 'claude' | 'codex') => { onOpenSettings(); setToolTab(tab); };
  return (
    <LoginContext.Provider value={{ state, pending, authenticated, usingAccount, applying, onRefresh, openLogin, useAccount, toolTab, selectToolTab, networkRequested, completeNetworkRequest }}>
      {children}
      <Modal title={t('claudeCodeConfig.deviceLoginStart')} open={open} onCancel={close} maskClosable={false} width={540}
        afterClose={() => {
          if (openNetworkOnClose.current) { openNetworkOnClose.current = false; setToolTab('codex'); onOpenSettings(); setNetworkRequested(true); }
        }}
        footer={<Space wrap>
          <Button onClick={close}>{t(pending ? 'claudeCodeConfig.deviceLoginCancel' : 'claudeCodeConfig.deviceLoginClose')}</Button>
          {state.status === 'error' || state.status === 'cancelled' ? <Button type="primary" onClick={() => send('start')}>{t('claudeCodeConfig.deviceLoginRetry')}</Button> : null}
          {state.status === 'waiting' ? <Button type="primary" icon={<LinkOutlined />} onClick={() => send('copyAndOpen')}>{t('claudeCodeConfig.deviceLoginCopyOpen')}</Button> : null}
          {state.status === 'success' && !usingAccount ? <Button type="primary" loading={applying} onClick={useAccount}>{t('claudeCodeConfig.deviceLoginUseAccount')}</Button> : null}
        </Space>}>
        {state.status === 'starting' ? (
          <div style={{ textAlign: 'center', padding: '32px 12px' }}>
            <Spin size="large" />
            <Typography.Paragraph style={{ marginTop: 18 }}>{t(state.phase === 'initializing' ? 'claudeCodeConfig.deviceLoginInitializing' : 'claudeCodeConfig.deviceLoginRequesting')}</Typography.Paragraph>
          </div>
        ) : null}
        {state.status === 'waiting' ? (
          <Space orientation="vertical" size={16} style={{ width: '100%', marginTop: 12 }}>
            <div style={{ width: '100%' }}>
              <Typography.Paragraph strong>{t('claudeCodeConfig.deviceLoginStepCode')}</Typography.Paragraph>
              <Space.Compact style={{ width: '100%' }}>
                <Input aria-label={t('claudeCodeConfig.deviceLoginCode')} readOnly value={state.userCode} style={{ fontFamily: 'monospace', fontSize: 22, letterSpacing: 3 }} onFocus={(event) => event.target.select()} />
                <Button icon={<CopyOutlined />} onClick={() => send('copy')} style={{ height: 'auto' }}>{t(copied === 'code' ? 'claudeCodeConfig.deviceLoginCopied' : 'claudeCodeConfig.deviceLoginCopy')}</Button>
              </Space.Compact>
            </div>
            <div>
              <Typography.Paragraph strong>{t('claudeCodeConfig.deviceLoginStepBrowser')}</Typography.Paragraph>
              <Typography.Paragraph type="secondary">{t('claudeCodeConfig.deviceLoginWaiting')}</Typography.Paragraph>
              <Space wrap>
                <Button size="small" type="link" style={{ paddingLeft: 0 }} onClick={() => send('open')}>{t('claudeCodeConfig.deviceLoginOpen')}</Button>
                <Button size="small" type="link" onClick={() => send('copyUrl')}>{t(copied === 'url' ? 'claudeCodeConfig.deviceLoginUrlCopied' : 'claudeCodeConfig.deviceLoginCopyUrl')}</Button>
              </Space>
              <Typography.Text type="secondary" style={{ display: 'block', fontSize: 12 }}>{state.verificationUrl}</Typography.Text>
            </div>
            <Alert type="info" showIcon title={t('claudeCodeConfig.deviceLoginAutomatic')} />
          </Space>
        ) : null}
        {state.status === 'success' ? <Alert style={{ marginTop: 12 }} type="success" icon={<CheckCircleOutlined />} showIcon title={t('claudeCodeConfig.deviceLoginSuccess')} description={t('claudeCodeConfig.deviceLoginSelectionHint')} /> : null}
        {actionError ? <Alert style={{ marginTop: 12 }} type="warning" showIcon title={t(`claudeCodeConfig.deviceLoginActionErrors.${actionError}`)} /> : null}
        {state.status === 'error' ? (
          <Space orientation="vertical" size={12} style={{ width: '100%', marginTop: 12 }}>
            <Alert type="error" showIcon title={t(`claudeCodeConfig.deviceLoginErrors.${errorKey}`, { status: state.httpStatus })}
              description={t(`claudeCodeConfig.deviceLoginErrorHints.${errorKey}`)} />
            <Space wrap>
              {networkError ? <Button onClick={() => { openNetworkOnClose.current = true; setOpen(false); }}>{t('claudeCodeConfig.deviceLoginNetworkSettings')}</Button> : null}
              <Button type="link" style={{ paddingLeft: networkError ? undefined : 0 }} onClick={() => send('help')}>{t('claudeCodeConfig.deviceLoginHelp')}</Button>
            </Space>
            <Collapse ghost size="small" items={[{ key: 'details', label: t('claudeCodeConfig.deviceLoginDetails'), children: (
              <Space orientation="vertical" size={4}>
                {state.phase ? <Typography.Text>{t('claudeCodeConfig.deviceLoginPhase', { phase: t(`claudeCodeConfig.deviceLoginPhases.${state.phase}`) })}</Typography.Text> : null}
                {state.httpStatus ? <Typography.Text>HTTP {state.httpStatus}</Typography.Text> : null}
                {state.rpcCode !== undefined ? <Typography.Text>{t('claudeCodeConfig.deviceLoginRpcCode', { code: state.rpcCode })}</Typography.Text> : null}
              </Space>
            ) }]} />
          </Space>
        ) : null}
        <Typography.Paragraph type="secondary" style={{ marginTop: 20, marginBottom: 0, fontSize: 12 }}>{t('claudeCodeConfig.deviceLoginHint')}</Typography.Paragraph>
      </Modal>
    </LoginContext.Provider>
  );
}

export function CodexDeviceLoginPanel({ t }: { t: TFunction }) {
  const { state, pending, authenticated, usingAccount, applying, onRefresh, openLogin, useAccount } = useCodexDeviceLogin();
  const loginLabel = t(pending ? 'claudeCodeConfig.deviceLoginContinue' : authenticated ? 'claudeCodeConfig.deviceLoginAgain' : 'claudeCodeConfig.deviceLoginStart');
  return (
    <section aria-label={t('claudeCodeConfig.codexAccountTitle')} style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--vscode-panel-border, #ddd)' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <Space wrap>
          <UserOutlined />
          <Typography.Text strong>{t('claudeCodeConfig.codexAccountTitle')}</Typography.Text>
          <Tag color={pending ? 'processing' : authenticated ? 'green' : 'default'} style={{ margin: 0 }}>
            {t(pending ? 'claudeCodeConfig.deviceLoginInProgress' : authenticated ? 'claudeCodeConfig.codexOfficialLoginPresent' : 'claudeCodeConfig.codexOfficialLoginMissing')}
          </Tag>
          {usingAccount && authenticated ? <Typography.Text type="secondary">{t('claudeCodeConfig.deviceLoginInUse')}</Typography.Text> : null}
        </Space>
        <Space wrap>
          {onRefresh ? <Button size="small" type="text" icon={<ReloadOutlined />} onClick={onRefresh} title={t('claudeCodeConfig.deviceLoginRefresh')} aria-label={t('claudeCodeConfig.deviceLoginRefresh')} /> : null}
          {authenticated && !usingAccount ? <Button size="small" loading={applying} onClick={useAccount}>{t('claudeCodeConfig.deviceLoginUseAccount')}</Button> : null}
          <Button size="small" type={authenticated ? 'default' : 'primary'} icon={<LoginOutlined />} aria-label={loginLabel}
            onClick={openLogin}>
            {loginLabel}
          </Button>
        </Space>
      </div>
      <Typography.Text type="secondary" style={{ display: 'block', marginTop: 6, fontSize: 12 }}>
        {t('claudeCodeConfig.codexAccountHint')}
      </Typography.Text>
    </section>
  );
}
