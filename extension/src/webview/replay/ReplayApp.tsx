/**
 * Replay App - Main component for simulation replay
 */

import * as React from 'react';
import { Button, ConfigProvider } from 'antd';
import { useTranslation } from 'react-i18next';
import type { ExtensionMessage, VSCodeAPI } from './types';
import { ReplayProvider, useReplay } from './store';
import { TimelinePlayer, AgentDetailPanel, AgentMap, AgentRightPanel } from './components';
import { useVscodeTheme } from '../theme';

interface ReplayAppProps {
  vscode: VSCodeAPI;
}

export const ReplayApp: React.FC<ReplayAppProps> = ({ vscode }) => {
  const { themeConfig } = useVscodeTheme();

  return (
    <ConfigProvider theme={themeConfig}>
      <ReplayProvider vscode={vscode}>
        <ReplayAppInner vscode={vscode} />
      </ReplayProvider>
    </ConfigProvider>
  );
};

const ReplayAppInner: React.FC<ReplayAppProps> = ({ vscode }) => {
  const { t } = useTranslation();
  const { state, actions } = useReplay();
  const {
    initialized,
    loading,
    error,
    initData,
    currentStep,
    timeline,
    experimentInfo,
  } = state;

  React.useEffect(() => {
    const handleMessage = (event: MessageEvent<ExtensionMessage>) => {
      const message = event.data;

      switch (message.type) {
        case 'init':
          actions.setInitData(message.data);
          actions.setLoading(true);
          vscode.postMessage({ command: 'fetchExperimentInfo' });
          vscode.postMessage({ command: 'fetchTimeline' });
          vscode.postMessage({ command: 'fetchAgentProfiles' });
          vscode.postMessage({ command: 'fetchPanelSchema' });
          break;

        case 'experimentInfo':
          actions.setExperimentInfo(message.data);
          break;

        case 'timeline':
          actions.setTimeline(message.data);
          actions.setInitialized(true);
          actions.setLoading(false);
          if (message.data.length > 0) {
            actions.setCurrentStep(0);
          }
          break;

        case 'agentProfiles':
          actions.setAgentProfiles(message.data);
          break;

        case 'panelSchema':
          actions.setPanelSchema(message.data);
          break;

        case 'stepBundle':
          actions.setStepBundle(message.data);
          break;

        case 'replayDatasetRows':
          actions.setReplayDatasetRows(message.requestKey ?? 'default', message.data);
          break;

        case 'error':
          actions.setError(message.message);
          actions.setLoading(false);
          break;

        default:
          break;
      }
    };

    window.addEventListener('message', handleMessage);
    vscode.postMessage({ command: 'ready' });
    return () => window.removeEventListener('message', handleMessage);
  }, [vscode, actions]);

  React.useEffect(() => {
    if (!initialized || timeline.length === 0 || currentStep >= timeline.length) {
      return;
    }
    const stepNumber = timeline[currentStep]?.step;
    if (stepNumber === undefined) {
      return;
    }
    vscode.postMessage({ command: 'fetchStepBundle', step: stepNumber });
  }, [currentStep, initialized, timeline, vscode]);

  // While a run is in progress and timeline is still empty, poll for markers.
  React.useEffect(() => {
    if (!initialized || timeline.length > 0) {
      return;
    }
    if (experimentInfo?.run_status !== 'running') {
      return;
    }
    const timer = window.setInterval(() => {
      if (document.hidden) { return; }
      vscode.postMessage({ command: 'fetchExperimentInfo' });
      vscode.postMessage({ command: 'fetchTimeline' });
    }, 5000);
    return () => window.clearInterval(timer);
  }, [initialized, timeline.length, experimentInfo?.run_status, vscode]);

  const refresh = () => {
    actions.setError(null);
    actions.setLoading(true);
    vscode.postMessage({ command: 'fetchExperimentInfo' });
    vscode.postMessage({ command: 'fetchTimeline' });
    vscode.postMessage({ command: 'fetchPanelSchema' });
    vscode.postMessage({ command: 'fetchAgentProfiles' });
  };

  if (error) {
    return (
      <div className="loading-container">
        <div style={{ fontSize: '48px' }}>⚠️</div>
        <div style={{ color: 'var(--vscode-errorForeground)' }}>{t('replay.errorTitle')}</div>
        <div role="alert" style={{ fontSize: '12px', maxWidth: '400px', textAlign: 'center' }}>{error}</div>
        <Button onClick={refresh}>{t('replay.retry')}</Button>
      </div>
    );
  }

  if (loading || !initialized) {
    return (
      <div className="loading-container">
        <div className="loading-spinner" />
        <div>{t('replay.loading')}</div>
        {initData && (
          <div style={{ fontSize: '12px', opacity: 0.7 }}>
            {t('replay.loadingExperiment', { id: initData.experimentId })}
          </div>
        )}
      </div>
    );
  }

  if (timeline.length === 0) {
    const info = experimentInfo;
    const status = info?.run_status ?? null;
    const completed = info?.pid_step_count ?? 0;
    let hint = t('replay.noDataHint');
    if (status === 'running') {
      hint = t('replay.noDataRunning', { completed });
    } else if (status === 'completed' || status === 'finished' || status === 'done') {
      hint = t('replay.noDataCompleted');
    } else if ((info?.registered_datasets ?? 0) > 0) {
      hint = t('replay.noDataRegistered', {
        datasets: info?.registered_datasets ?? 0,
        nonempty: info?.nonempty_snapshot_tables ?? 0,
      });
    }
    return (
      <div className="loading-container">
        <div style={{ fontSize: '48px' }}>📭</div>
        <div>{t('replay.noData')}</div>
        <div style={{ fontSize: '12px', opacity: 0.7, maxWidth: '420px', textAlign: 'center' }}>
          {hint}
        </div>
        <Button style={{ marginTop: 12 }} onClick={refresh}>{t('replay.refreshTimeline')}</Button>
      </div>
    );
  }

  return (
    <div className="replay-container">
      <div className="deck">
        <AgentMap />
      </div>
      <div className="agentsociety-left">
        <AgentDetailPanel />
      </div>
      <div className="agentsociety-right">
        <AgentRightPanel />
      </div>
      <div className="control-progress">
        <TimelinePlayer />
      </div>
    </div>
  );
};
