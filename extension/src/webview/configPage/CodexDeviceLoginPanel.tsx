import * as React from 'react';
import { Alert, Button, Space, Typography } from 'antd';
import { CopyOutlined, LinkOutlined } from '@ant-design/icons';
import type { TFunction } from 'i18next';
import type { VSCodeAPI } from './types';
import type { CodexDeviceLoginState } from '../../services/codexDeviceLogin';

export function CodexDeviceLoginPanel({ t, vscode, loggedIn, onUseAccount, applying }: {
  t: TFunction;
  vscode: VSCodeAPI;
  loggedIn: boolean;
  onUseAccount: () => void;
  applying: boolean;
}) {
  const [state, setState] = React.useState<CodexDeviceLoginState>({ status: 'idle' });
  const [copied, setCopied] = React.useState(false);
  const [actionError, setActionError] = React.useState(false);
  React.useEffect(() => {
    const receive = (event: MessageEvent) => {
      if (event.data?.command === 'codexDeviceLoginState') {
        setState(event.data.state);
        setCopied(false);
        setActionError(false);
      } else if (event.data?.command === 'codexDeviceLoginCopied') {
        setCopied(true);
      } else if (event.data?.command === 'codexDeviceLoginActionError') {
        setActionError(true);
      }
    };
    window.addEventListener('message', receive);
    vscode.postMessage({ command: 'codexDeviceLogin', action: 'status' });
    return () => window.removeEventListener('message', receive);
  }, [vscode]);
  const send = (action: string) => {
    setActionError(false);
    vscode.postMessage({ command: 'codexDeviceLogin', action });
  };
  const pending = state.status === 'starting' || state.status === 'waiting';

  return (
    <div style={{ marginTop: 10 }}>
      <Space wrap>
        <Button size="small" loading={state.status === 'starting'} disabled={state.status === 'waiting'} onClick={() => send('start')}>
          {t(loggedIn ? 'claudeCodeConfig.deviceLoginAgain' : 'claudeCodeConfig.deviceLoginStart')}
        </Button>
        {pending ? <Button size="small" onClick={() => send('cancel')}>{t('claudeCodeConfig.deviceLoginCancel')}</Button> : null}
        {loggedIn || state.status === 'success' ? <Button size="small" onClick={onUseAccount} loading={applying}>{t('claudeCodeConfig.deviceLoginUseAccount')}</Button> : null}
        <Typography.Text type="secondary" style={{ fontSize: 11 }}>{t('claudeCodeConfig.deviceLoginHint')}</Typography.Text>
      </Space>
      {state.status === 'waiting' ? (
        <Alert style={{ marginTop: 8 }} type="info" title={t('claudeCodeConfig.deviceLoginWaiting')} description={
          <Space orientation="vertical" size={8}>
            <Typography.Text code style={{ fontSize: 20, letterSpacing: 2 }}>{state.userCode}</Typography.Text>
            <Space wrap>
              <Button size="small" type="primary" icon={<LinkOutlined />} onClick={() => send('copyAndOpen')}>{t('claudeCodeConfig.deviceLoginCopyOpen')}</Button>
              <Button size="small" icon={<CopyOutlined />} onClick={() => send('copy')}>{t(copied ? 'claudeCodeConfig.deviceLoginCopied' : 'claudeCodeConfig.deviceLoginCopy')}</Button>
              <Button size="small" onClick={() => send('open')}>{t('claudeCodeConfig.deviceLoginOpen')}</Button>
            </Space>
            <Typography.Text type="secondary">{state.verificationUrl}</Typography.Text>
            <Typography.Text>{t('claudeCodeConfig.deviceLoginEnableHint')}</Typography.Text>
          </Space>
        } />
      ) : null}
      {state.status === 'success' ? <Alert style={{ marginTop: 8 }} type="success" showIcon title={t('claudeCodeConfig.deviceLoginSuccess')} description={t('claudeCodeConfig.deviceLoginSelectionHint')} /> : null}
      {actionError ? <Alert style={{ marginTop: 8 }} type="warning" showIcon title={t('claudeCodeConfig.deviceLoginActionError')} /> : null}
      {state.status === 'cancelled' ? <Typography.Text type="secondary" style={{ display: 'block', marginTop: 8 }}>{t('claudeCodeConfig.deviceLoginCancelled')}</Typography.Text> : null}
      {state.status === 'error' ? <Alert style={{ marginTop: 8 }} type="error" showIcon title={t(`claudeCodeConfig.deviceLoginErrors.${state.error}`)} description={t('claudeCodeConfig.deviceLoginRetryHint')} /> : null}
    </div>
  );
}
