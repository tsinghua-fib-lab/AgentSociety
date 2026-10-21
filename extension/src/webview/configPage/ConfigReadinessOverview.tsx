import * as React from 'react';
import { Tag, Tooltip, Typography } from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  KeyOutlined,
  LinkOutlined,
  LoadingOutlined,
  StopOutlined,
} from '@ant-design/icons';
import type { TFunction } from 'i18next';
import type { VscodeThemePalette } from '../theme';
import type { AiCliGatewayStatus } from './claudeCodeTypes';
import type { TokenUsageRecord } from './gatewayUsageTypes';
import { formatTokenCount, resolveGatewayUsageView } from './gatewayUsageView';
import type { BackendStatus, ValidationState } from './types';

const { Text } = Typography;

type Props = {
  t: TFunction;
  palette: VscodeThemePalette;
  isDark: boolean;
  hasWorkspace: boolean;
  hasLlmKey: boolean;
  llmModel: string;
  defaultValidation: ValidationState;
  backendStatus: BackendStatus;
  gatewayStatus: AiCliGatewayStatus;
  gatewayUsageRecords?: TokenUsageRecord[];
  onOpenSimulation: () => void;
  onOpenBackendUrl?: (url: string) => void;
  onStartBackend?: () => void;
  onOpenCli?: () => void;
  backendStarting?: boolean;
};

export function ConfigReadinessOverview({
  t,
  palette,
  isDark,
  hasWorkspace,
  hasLlmKey,
  llmModel,
  defaultValidation,
  backendStatus,
  gatewayStatus,
  gatewayUsageRecords = [],
  onOpenSimulation,
  onOpenBackendUrl,
  onStartBackend,
  onOpenCli,
  backendStarting = false,
}: Props) {
  const cardBase: React.CSSProperties = {
    borderRadius: 10,
    border: `1px solid ${palette.panelBorder}`,
    backdropFilter: 'blur(16px)',
    WebkitBackdropFilter: 'blur(16px)',
    boxShadow: '0 2px 8px rgba(0,0,0,0.06)',
    flex: '1 1 160px',
    minWidth: 140,
    padding: '12px 14px',
    background: isDark ? 'rgba(37, 37, 38, 0.6)' : 'rgba(255, 255, 255, 0.55)',
  };

  const llmMetric = React.useMemo(() => {
    if (!hasWorkspace) {
      return {
        value: t('configPage.metrics.noWorkspace'),
        accent: palette.descriptionForeground,
        hint: undefined as string | undefined,
      };
    }
    if (!hasLlmKey) {
      return {
        value: t('configPage.readiness.modelMissing'),
        accent: palette.descriptionForeground,
        hint: t('configPage.metrics.llmHintMissing'),
      };
    }
    const name = llmModel.trim() || t('configPage.readiness.modelUnset');
    if (defaultValidation.validating) {
      return {
        value: name,
        accent: palette.linkForeground,
        hint: t('configPage.validating'),
      };
    }
    if (defaultValidation.valid === true) {
      return {
        value: name,
        accent: palette.successForeground,
        hint: t('configPage.readiness.metricModelOk'),
      };
    }
    if (defaultValidation.valid === false) {
      return {
        value: name,
        accent: palette.errorForeground,
        hint: defaultValidation.error ?? t('configPage.advancedValidation.statusErrorShort'),
      };
    }
    return {
      value: name,
      accent: palette.warningForeground,
      hint: t('configPage.advancedValidation.statusIdleShort'),
    };
  }, [
    defaultValidation.error,
    defaultValidation.valid,
    defaultValidation.validating,
    hasLlmKey,
    hasWorkspace,
    llmModel,
    palette,
    t,
  ]);

  const validationTag = React.useMemo(() => {
    if (!hasLlmKey) {
      return null;
    }
    if (defaultValidation.validating) {
      return (
        <Tag icon={<LoadingOutlined spin />} color="processing" style={{ margin: 0 }}>
          {t('configPage.validating')}
        </Tag>
      );
    }
    if (defaultValidation.valid === true) {
      return (
        <Tag icon={<CheckCircleOutlined />} color="success" style={{ margin: 0 }}>
          {t('configPage.metrics.validationPass')}
        </Tag>
      );
    }
    if (defaultValidation.valid === false) {
      return (
        <Tag icon={<CloseCircleOutlined />} color="error" style={{ margin: 0 }}>
          {t('configPage.metrics.validationFail')}
        </Tag>
      );
    }
    return (
      <Tag color="default" style={{ margin: 0 }}>
        {t('configPage.advancedValidation.statusIdleShort')}
      </Tag>
    );
  }, [defaultValidation.valid, defaultValidation.validating, hasLlmKey, t]);

  const gatewayMetric = React.useMemo(() => {
    if (!gatewayStatus.enabled) {
      return null;
    }
    if (gatewayStatus.running) {
      const uptime =
        gatewayStatus.stats?.uptimeMs != null
          ? t('configPage.metrics.uptime', {
            duration: formatWebviewDuration(gatewayStatus.stats.uptimeMs),
          })
          : null;
      const requests =
        gatewayStatus.stats?.totalRequests != null
          ? t('configPage.metrics.requests', { count: gatewayStatus.stats.totalRequests })
          : null;
      const usageView = resolveGatewayUsageView(gatewayUsageRecords, { range: '7d', app: 'all' });
      const tokens =
        usageView && (usageView.totalInputTokens > 0 || usageView.totalOutputTokens > 0)
          ? `${t('claudeCodeConfig.usageColInput')} ${formatTokenCount(usageView.totalInputTokens)} · ${t('claudeCodeConfig.usageColOutput')} ${formatTokenCount(usageView.totalOutputTokens)}`
          : null;
      return {
        value: t('configPage.readiness.gatewayOn', { port: gatewayStatus.port ?? '' }),
        accent: palette.successForeground,
        hint: [uptime, requests, tokens].filter(Boolean).join(' · ') || undefined,
      };
    }
    return {
      value: t('configPage.metrics.gatewayStopped'),
      accent: palette.warningForeground,
      hint: gatewayStatus.error ?? t('configPage.metrics.gatewayStoppedHint'),
    };
  }, [gatewayStatus, gatewayUsageRecords, palette, t]);

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
      <MetricCard
        cardBase={cardBase}
        palette={palette}
        label={t('configPage.readiness.metricModel')}
        value={llmMetric.value}
        accent={llmMetric.accent}
        icon={<KeyOutlined />}
        onClick={onOpenSimulation}
        hint={llmMetric.hint}
        footer={validationTag}
      />
      <MetricCard
        cardBase={cardBase}
        palette={palette}
        label={t('configPage.overview.backend')}
        value={
          backendStatus.isRunning
            ? t('configPage.overview.backendRunning', { port: backendStatus.port ?? '' })
            : t('configPage.overview.backendStopped')
        }
        accent={backendStatus.isRunning ? palette.successForeground : palette.descriptionForeground}
        icon={
          backendStarting ? (
            <LoadingOutlined spin />
          ) : backendStatus.isRunning ? (
            <CheckCircleOutlined />
          ) : (
            <StopOutlined />
          )
        }
        onClick={
          backendStatus.isRunning && backendStatus.url
            ? () => onOpenBackendUrl?.(backendStatus.url!)
            : !backendStatus.isRunning && onStartBackend && !backendStarting
              ? onStartBackend
              : undefined
        }
        hint={
          backendStatus.isRunning
            ? undefined
            : backendStarting
              ? t('configPage.starting')
              : t('configPage.overview.backendStoppedHint')
        }
        footer={
          backendStatus.isRunning && backendStatus.url ? (
            <Text
              style={{ fontSize: 11, color: palette.linkForeground, cursor: 'pointer' }}
              onClick={(event) => {
                event.stopPropagation();
                onOpenBackendUrl?.(backendStatus.url!);
              }}
            >
              <LinkOutlined style={{ marginRight: 4 }} />
              {backendStatus.url}
            </Text>
          ) : null
        }
      />
      {gatewayMetric ? (
        <MetricCard
          cardBase={cardBase}
          palette={palette}
          label={t('configPage.readiness.metricGateway')}
          value={gatewayMetric.value}
          accent={gatewayMetric.accent}
          icon={<CheckCircleOutlined />}
          onClick={onOpenCli}
          hint={gatewayMetric.hint}
        />
      ) : null}
    </div>
  );
}

function formatWebviewDuration(ms: number): string {
  const totalSec = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(totalSec / 3600);
  const minutes = Math.floor((totalSec % 3600) / 60);
  const seconds = totalSec % 60;
  if (hours > 0) {
    return `${hours}h${minutes}m`;
  }
  if (minutes > 0) {
    return `${minutes}m${seconds}s`;
  }
  return `${seconds}s`;
}

function MetricCard({
  palette,
  cardBase,
  label,
  value,
  accent,
  icon,
  onClick,
  hint,
  footer,
}: {
  palette: VscodeThemePalette;
  cardBase: React.CSSProperties;
  label: string;
  value: string;
  accent?: string;
  icon: React.ReactNode;
  onClick?: () => void;
  hint?: string;
  footer?: React.ReactNode;
}) {
  const body = (
    <div
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onClick={onClick}
      style={{
        ...cardBase,
        cursor: onClick ? 'pointer' : undefined,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
        <span style={{ color: accent ?? palette.linkForeground }}>{icon}</span>
        <span style={{ fontSize: 11, color: palette.descriptionForeground, fontWeight: 500 }}>{label}</span>
      </div>
      <div
        style={{
          fontSize: 15,
          fontWeight: 600,
          color: accent ?? palette.editorForeground,
          lineHeight: 1.3,
          wordBreak: 'break-all',
        }}
      >
        {value}
      </div>
      {hint ? (
        <Text type="secondary" style={{ fontSize: 11, display: 'block', marginTop: 4 }}>
          {hint}
        </Text>
      ) : null}
      {footer ? <div style={{ marginTop: 6 }}>{footer}</div> : null}
    </div>
  );
  return hint && onClick ? <Tooltip title={hint}>{body}</Tooltip> : body;
}
