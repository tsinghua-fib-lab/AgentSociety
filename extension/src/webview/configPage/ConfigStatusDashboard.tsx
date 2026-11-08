import * as React from 'react';
import { Space, Tag, Typography } from 'antd';
import {
  ApiOutlined,
  CheckCircleOutlined,
  KeyOutlined,
  RightOutlined,
  LoadingOutlined,
  StopOutlined,
} from '@ant-design/icons';
import type { TFunction } from 'i18next';
import type { VscodeThemePalette } from '../theme';
import type { AiCliGatewayStatus } from './claudeCodeTypes';
import { GatewayUsageTrendCard } from './GatewayUsageTrendCard';
import type { TokenUsageRecord } from './gatewayUsageTypes';
import { formatTokenCount, resolveGatewayUsageView } from './gatewayUsageView';
import type { BackendStatus, ValidationState } from './types';

const { Text, Title } = Typography;

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
  gatewayUsageRecords: TokenUsageRecord[];
  showUsageChart: boolean;
  usageLoading?: boolean;
  onOpenSimulation: () => void;
  onOpenBackendUrl?: (url: string) => void;
  onStartBackend?: () => void;
  onOpenCli?: () => void;
  backendStarting?: boolean;
};

function formatDuration(ms: number): string {
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

export function ConfigStatusDashboard({
  t,
  palette,
  isDark,
  hasWorkspace,
  hasLlmKey,
  llmModel,
  defaultValidation,
  backendStatus,
  gatewayStatus,
  gatewayUsageRecords,
  showUsageChart,
  usageLoading = false,
  onOpenSimulation,
  onOpenBackendUrl,
  onStartBackend,
  onOpenCli,
  backendStarting = false,
}: Props) {
  const panelBg = palette.surfaceMuted;

  const llmLine = React.useMemo(() => {
    if (!hasWorkspace) {
      return { title: t('configPage.metrics.noWorkspace'), sub: undefined, accent: palette.descriptionForeground };
    }
    if (!hasLlmKey) {
      return { title: t('configPage.readiness.modelMissing'), sub: t('configPage.metrics.llmHintMissing'), accent: palette.descriptionForeground };
    }
    const name = llmModel.trim() || t('configPage.readiness.modelUnset');
    if (defaultValidation.validating) {
      return { title: name, sub: t('configPage.validating'), accent: palette.linkForeground };
    }
    if (defaultValidation.valid === true) {
      return { title: name, sub: t('configPage.readiness.metricModelOk'), accent: palette.successForeground };
    }
    if (defaultValidation.valid === false) {
      return {
        title: name,
        sub: defaultValidation.error ?? t('configPage.advancedValidation.statusErrorShort'),
        accent: palette.errorForeground,
      };
    }
    return { title: name, sub: t('configPage.advancedValidation.statusIdleShort'), accent: palette.warningForeground };
  }, [defaultValidation, hasLlmKey, hasWorkspace, llmModel, palette, t]);

  const gatewayLine = React.useMemo(() => {
    if (!gatewayStatus.enabled) {
      return {
        title: t('configPage.metrics.gatewayDisabled'),
        sub: t('configPage.metrics.gatewayDisabledHint'),
        accent: palette.descriptionForeground,
        icon: <ApiOutlined />,
      };
    }
    if (gatewayStatus.running) {
      const uptime =
        gatewayStatus.stats?.uptimeMs != null
          ? t('configPage.metrics.uptime', { duration: formatDuration(gatewayStatus.stats.uptimeMs) })
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
        title: t('configPage.readiness.gatewayOn', { port: gatewayStatus.port ?? '' }),
        sub: [uptime, requests, tokens].filter(Boolean).join(' · '),
        accent: palette.successForeground,
        icon: <CheckCircleOutlined />,
      };
    }
    return {
      title: t('configPage.metrics.gatewayStopped'),
      sub: gatewayStatus.error ?? t('configPage.metrics.gatewayStoppedHint'),
      accent: palette.warningForeground,
      icon: <ApiOutlined />,
    };
  }, [gatewayStatus, gatewayUsageRecords, palette, t]);

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 220px), 1fr))',
          gap: 14,
        }}
      >
        <StatusTile
          palette={palette}
          background={panelBg}
          label={t('configPage.readiness.metricGateway')}
          title={gatewayLine.title}
          subtitle={gatewayLine.sub}
          accent={gatewayLine.accent}
          icon={gatewayLine.icon}
          onClick={onOpenCli}
        />
        <StatusTile
          palette={palette}
          background={panelBg}
          label={t('configPage.overview.backend')}
          title={
            backendStatus.isRunning
              ? t('configPage.overview.backendRunning', { port: backendStatus.port ?? '' })
              : t('configPage.overview.backendStopped')
          }
          subtitle={
            backendStatus.isRunning
              ? backendStatus.url
              : backendStarting ? t('configPage.starting') : t('configPage.overview.backendStoppedHint')
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
        />
        <StatusTile
          palette={palette}
          background={panelBg}
          label={t('configPage.readiness.metricModel')}
          title={llmLine.title}
          subtitle={llmLine.sub}
          accent={llmLine.accent}
          icon={<KeyOutlined />}
          onClick={onOpenSimulation}
          footer={
            hasLlmKey && defaultValidation.valid === true ? (
              <Tag icon={<CheckCircleOutlined />} color="success" style={{ margin: 0 }}>
                {t('configPage.metrics.validationPass')}
              </Tag>
            ) : null
          }
        />
      </div>

      {showUsageChart && gatewayStatus.enabled ? (
        <GatewayUsageTrendCard
          t={t}
          palette={palette}
          background={panelBg}
          records={gatewayUsageRecords}
          loading={usageLoading}
          range="7d"
          title={t('configPage.dashboard.claudeUsageTitle')}
          subtitle={t('configPage.dashboard.claudeUsageSubtitle')}
        />
      ) : null}
    </Space>
  );
}

function StatusTile({
  palette,
  background,
  label,
  title,
  subtitle,
  accent,
  icon,
  onClick,
  footer,
}: {
  palette: VscodeThemePalette;
  background: string;
  label: string;
  title: string;
  subtitle?: string;
  accent: string;
  icon: React.ReactNode;
  onClick?: () => void;
  footer?: React.ReactNode;
}) {
  return (
    <div
      className={onClick ? 'as-interactive-card' : undefined}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onClick={onClick}
      onKeyDown={(event) => {
        if (onClick && event.target === event.currentTarget && (event.key === 'Enter' || event.key === ' ')) {
          event.preventDefault();
          onClick();
        }
      }}
      style={{
        borderRadius: 16,
        border: `1px solid ${palette.panelBorder}`,
        background,
        padding: '18px 20px',
        cursor: onClick ? 'pointer' : undefined,
        minHeight: 120,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <span style={{ color: accent, fontSize: 18 }}>{icon}</span>
        <Text type="secondary" style={{ fontSize: 12, fontWeight: 500 }}>
          {label}
        </Text>
        {onClick ? <RightOutlined aria-hidden style={{ marginLeft: 'auto', color: palette.descriptionForeground, fontSize: 12 }} /> : null}
      </div>
      <Title level={4} style={{ margin: 0, color: accent, fontSize: 20, lineHeight: 1.25, wordBreak: 'break-all' }}>
        {title}
      </Title>
      {subtitle ? (
        <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
          {subtitle}
        </Text>
      ) : null}
      {footer ? <div style={{ marginTop: 10 }}>{footer}</div> : null}
    </div>
  );
}
