import * as React from 'react';
import {
  Alert,
  Button,
  Input,
  InputNumber,
  Modal,
  Segmented,
  Space,
  Spin,
  Table,
  Typography,
} from 'antd';
import {
  BarChartOutlined,
  ClearOutlined,
  DeleteOutlined,
  ReloadOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import type { TFunction } from 'i18next';
import type { VscodeThemePalette } from '../theme';
import type { AiCliGatewayStatus } from './claudeCodeTypes';
import type { TokenUsageRecord } from './gatewayUsageTypes';
import { calculateCost, formatCost, getModelPrice, type ModelPricingMap } from './modelPricing';
import { GatewayUsageChart } from './GatewayUsageChart';
import {
  aggregateGatewayUsage,
  aggregateByProvider,
  buildUsageChartSeries,
  computeUsageSuccessRate,
  emptyAggregation,
  filterProbeRecords,
  filterRecordsByApp,
  filterRecordsByRange,
  formatChartCost,
  formatTokenCount,
  hasChatUsageRecords,
  isProbeUsageRecord,
  localDateKey,
  recordApp,
  resolveRecordProvider,
  selectAccountingRecords,
  type UsageAppFilter,
  type UsageRangeFilter,
  type UsageTrendMetric,
} from './gatewayUsageView';

const { Text } = Typography;

function metricTone(color: string): React.CSSProperties {
  return {
    fontSize: 22,
    lineHeight: 1.15,
    fontWeight: 650,
    color,
    letterSpacing: '-0.02em',
  };
}

export interface GatewayUsagePanelProps {
  t: TFunction;
  palette: VscodeThemePalette;
  gatewayStatus?: AiCliGatewayStatus;
  records: TokenUsageRecord[];
  loading: boolean;
  onRefresh: () => void;
  onClear: () => void;
  customPricing: ModelPricingMap;
  onGetPricing: () => void;
  onRefreshPricing: () => void;
  onSavePricing: (pricing: ModelPricingMap) => void;
  onClearPricing: () => void;
  /** Only show filters/cards for these apps. Empty hides Claude/Codex cards. */
  enabledApps?: ReadonlyArray<'claude' | 'codex'>;
}

export function GatewayUsagePanel({
  t,
  palette,
  gatewayStatus,
  records,
  loading,
  onRefresh,
  onClear,
  customPricing,
  onGetPricing,
  onRefreshPricing,
  onSavePricing,
  onClearPricing,
  enabledApps,
}: GatewayUsagePanelProps) {
  const visibleApps = React.useMemo(
    (): ReadonlyArray<'claude' | 'codex'> => enabledApps ?? ['claude', 'codex'],
    [enabledApps]
  );
  const [pricingModalOpen, setPricingModalOpen] = React.useState(false);
  const [editingPricing, setEditingPricing] = React.useState<ModelPricingMap>({});
  const [trendMetric, setTrendMetric] = React.useState<UsageTrendMetric>('tokens');
  const [appFilter, setAppFilter] = React.useState<UsageAppFilter>('all');
  const [rangeFilter, setRangeFilter] = React.useState<UsageRangeFilter>('7d');
  const [detailView, setDetailView] = React.useState<'overview' | 'requests' | 'providers'>('overview');

  React.useEffect(() => {
    if (appFilter === 'all') {
      return;
    }
    if (!visibleApps.includes(appFilter)) {
      setAppFilter(visibleApps.length === 1 ? visibleApps[0] : 'all');
    }
  }, [appFilter, visibleApps]);
  const rangeRecords = React.useMemo(
    () => filterRecordsByRange(records, rangeFilter),
    [rangeFilter, records]
  );
  const chatRangeRecords = React.useMemo(
    () => selectAccountingRecords(filterProbeRecords(rangeRecords)),
    [rangeRecords]
  );
  const probeCountInRange = rangeRecords.length - chatRangeRecords.length;
  const hasAnyRecords = chatRangeRecords.length > 0;
  const rangeIsEmpty = records.length > 0 && rangeRecords.length === 0;
  const showProbeOnlyWarning =
    rangeRecords.length > 0 && !hasChatUsageRecords(rangeRecords);
  const showClaudeRouteWarning =
    Boolean(gatewayStatus?.running) &&
    gatewayStatus?.routeClaude === false &&
    (gatewayStatus?.claudeProxyAvailable ?? true);
  const scopedRecords = React.useMemo(() => {
    if (visibleApps.length === 0) {
      return chatRangeRecords;
    }
    return chatRangeRecords.filter((record) => visibleApps.includes(recordApp(record)));
  }, [chatRangeRecords, visibleApps]);
  const totalAggregation = React.useMemo(
    () => aggregateGatewayUsage(scopedRecords) ?? (hasAnyRecords ? emptyAggregation() : null),
    [scopedRecords, hasAnyRecords]
  );
  const filteredRecords = React.useMemo(() => {
    if (appFilter === 'all' || visibleApps.length === 0) {
      return scopedRecords;
    }
    return filterRecordsByApp(scopedRecords, appFilter);
  }, [appFilter, scopedRecords, visibleApps.length]);
  const viewAggregation = React.useMemo(
    () => aggregateGatewayUsage(filteredRecords) ?? (filteredRecords.length > 0 ? emptyAggregation() : null),
    [filteredRecords]
  );

  const detectedPricing = React.useMemo(() => {
    const detected: ModelPricingMap = {};
    for (const record of rangeRecords) {
      const price = getModelPrice(record.model, customPricing);
      if (price) {
        detected[record.model] = price;
      }
    }
    return detected;
  }, [customPricing, rangeRecords]);

  const openPricing = React.useCallback(() => {
    setEditingPricing({ ...detectedPricing, ...customPricing });
    onGetPricing();
    setPricingModalOpen(true);
  }, [customPricing, detectedPricing, onGetPricing]);

  const totalCost = React.useMemo(
    () =>
      filteredRecords.reduce((sum, r) => {
        const cost = calculateCost(
          r.model,
          r.inputTokens,
          r.outputTokens,
          r.cacheReadTokens,
          r.cacheCreationTokens,
          customPricing,
          {
            app: recordApp(r),
            reportedCostUsd: r.reportedCostUsd,
            cacheCreationLongTokens: r.cacheCreationLongTokens,
          }
        );
        return sum + (cost?.total ?? 0);
      }, 0),
    [filteredRecords, customPricing]
  );
  const pricedRecords = React.useMemo(
    () => filteredRecords.filter(
      (record) => record.reportedCostUsd !== undefined || getModelPrice(record.model, customPricing) !== null
    ).length,
    [filteredRecords, customPricing]
  );

  const cacheSavings = React.useMemo(
    () =>
      filteredRecords.reduce((sum, r) => {
        const price = getModelPrice(r.model, customPricing);
        if (!price) {
          return sum;
        }
        const fullInputCost = (r.cacheReadTokens / 1_000_000) * price.inputPerMillion;
        const cacheCost = price.cacheReadPerMillion
          ? (r.cacheReadTokens / 1_000_000) * price.cacheReadPerMillion
          : 0;
        return sum + Math.max(0, fullInputCost - cacheCost);
      }, 0),
    [filteredRecords, customPricing]
  );

  const costByBucket = React.useMemo(() => {
    if (!viewAggregation?.timeSeries.length) {
      return [];
    }
    const keys = viewAggregation.timeSeries.map((b) => b.key);
    const map = new Map<string, number>();
    for (const k of keys) {
      map.set(k, 0);
    }
    for (const r of filteredRecords) {
      const dayKey = localDateKey(r.ts);
      const matchKey = map.has(dayKey) ? dayKey : '';
      if (!matchKey) {
        continue;
      }
      const cost = calculateCost(
        r.model,
        r.inputTokens,
        r.outputTokens,
        r.cacheReadTokens,
        r.cacheCreationTokens,
        customPricing,
        {
          app: recordApp(r),
          reportedCostUsd: r.reportedCostUsd,
          cacheCreationLongTokens: r.cacheCreationLongTokens,
        }
      );
      map.set(matchKey, (map.get(matchKey) ?? 0) + (cost?.total ?? 0));
    }
    return viewAggregation.timeSeries.map((b) => map.get(b.key) ?? 0);
  }, [viewAggregation, filteredRecords, customPricing]);
  const successRate = React.useMemo(
    () => computeUsageSuccessRate(filteredRecords),
    [filteredRecords]
  );
  const providerRows = React.useMemo(
    () => aggregateByProvider(filteredRecords),
    [filteredRecords]
  );
  const requestRows = React.useMemo(
    () =>
      [...rangeRecords]
        .sort((a, b) => Date.parse(b.ts) - Date.parse(a.ts))
        .slice(0, 200)
        .map((record, index) => ({
          ...record,
          key: record.requestId || `${record.ts}-${index}`,
        })),
    [rangeRecords]
  );

  const usageToolbar = (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
      <Space>
        <BarChartOutlined />
        <Text strong style={{ fontSize: 13 }}>{t('claudeCodeConfig.usageTitle')}</Text>
      </Space>
      <Space size={[8, 6]} wrap>
        <Segmented
          size="small"
          value={rangeFilter}
          onChange={(value) => setRangeFilter(value as UsageRangeFilter)}
          options={[
            { label: t('claudeCodeConfig.usageRangeToday'), value: 'today' },
            { label: t('claudeCodeConfig.usageRange7d'), value: '7d' },
            { label: t('claudeCodeConfig.usageRange30d'), value: '30d' },
            { label: t('claudeCodeConfig.usageRangeAll'), value: 'all' },
          ]}
        />
        <Button size="small" icon={<SettingOutlined />} onClick={openPricing}>
          {t('claudeCodeConfig.usagePricingTitle')}
        </Button>
        <Button size="small" icon={<ReloadOutlined />} loading={loading} onClick={onRefresh}>
          {t('claudeCodeConfig.usageRefresh')}
        </Button>
        <Button size="small" danger icon={<ClearOutlined />} onClick={onClear}>
          {t('claudeCodeConfig.usageClear')}
        </Button>
      </Space>
    </div>
  );

  if (!hasAnyRecords && !loading) {
    return (
      <div>
        {usageToolbar}
        {showProbeOnlyWarning ? (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 12 }}
            message={t('claudeCodeConfig.usageProbeOnlyTitle')}
            description={t('claudeCodeConfig.usageProbeOnlyDesc', { count: probeCountInRange })}
          />
        ) : null}
        {showClaudeRouteWarning ? (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
            message={t('claudeCodeConfig.usageClaudeRouteOffTitle')}
            description={t('claudeCodeConfig.usageClaudeRouteOffDesc')}
          />
        ) : null}
        <div style={{ textAlign: 'center', padding: 20 }}>
          <Text type="secondary">
            {showProbeOnlyWarning
              ? t('claudeCodeConfig.usageProbeOnlyEmpty')
              : rangeIsEmpty
                ? t('claudeCodeConfig.usageRangeEmpty')
                : t('claudeCodeConfig.usageNoData')}
          </Text>
        </div>
      </div>
    );
  }

  if (!totalAggregation) {
    return (
      <div>
        {usageToolbar}
        <div style={{ textAlign: 'center', padding: 20 }}>
          <Spin />
        </div>
      </div>
    );
  }

  const activeAggregation = viewAggregation ?? emptyAggregation();
  const requestsChart = buildUsageChartSeries(activeAggregation, 'requests', t, palette);
  const tokensChart = buildUsageChartSeries(activeAggregation, 'tokens', t, palette);
  const costChart = buildUsageChartSeries(activeAggregation, 'cost', t, palette, costByBucket);
  const labels = requestsChart.labels;
  const hasTrend = labels.length >= 2;
  const averageTokens = activeAggregation.totalRequests > 0
    ? activeAggregation.totalTokens / activeAggregation.totalRequests
    : 0;
  const directTokens = activeAggregation.totalInputTokens + activeAggregation.totalOutputTokens;
  const outputRatio = directTokens > 0
    ? (activeAggregation.totalOutputTokens / directTokens) * 100
    : 0;
  const tokenParts = [
    {
      id: 'input',
      label: t('claudeCodeConfig.usageColInput'),
      value: activeAggregation.totalInputTokens,
      color: '#1677ff',
    },
    {
      id: 'output',
      label: t('claudeCodeConfig.usageColOutput'),
      value: activeAggregation.totalOutputTokens,
      color: '#52c41a',
    },
    {
      id: 'cacheRead',
      label: t('claudeCodeConfig.usageCacheRead'),
      value: activeAggregation.totalCacheReadTokens,
      color: '#722ed1',
    },
    {
      id: 'cacheCreate',
      label: t('claudeCodeConfig.usageCacheCreation'),
      value: activeAggregation.totalCacheCreationTokens,
      color: '#fa8c16',
    },
  ].filter((part) => part.value > 0);
  const tokenPartsTotal = tokenParts.reduce((sum, part) => sum + part.value, 0);

  const modelColumns = [
    {
      title: t('claudeCodeConfig.usageColModel'),
      dataIndex: 'model',
      key: 'model',
      render: (model: string, row: { requests: number }) => (
        <Space direction="vertical" size={0}>
          <Text style={{ fontSize: 12, fontWeight: 500 }}>{model}</Text>
          <Text type="secondary" style={{ fontSize: 11 }}>
            {row.requests} {t('claudeCodeConfig.usageRequests')}
          </Text>
        </Space>
      ),
    },
    {
      title: t('claudeCodeConfig.usageTotalTokens'),
      key: 'total',
      width: 150,
      render: (_: unknown, row: { total: number }) => {
        const share = activeAggregation.totalTokens > 0 ? (row.total / activeAggregation.totalTokens) * 100 : 0;
        return (
          <div style={{ minWidth: 100 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: 11 }}>
              <Text style={{ fontSize: 11 }}>{formatTokenCount(row.total)}</Text>
              <Text type="secondary" style={{ fontSize: 10 }}>{share.toFixed(1)}%</Text>
            </div>
            <div style={{ height: 3, borderRadius: 2, background: palette.panelBorder, marginTop: 4 }}>
              <div style={{ height: 3, borderRadius: 2, background: '#1677ff', width: `${share}%` }} />
            </div>
          </div>
        );
      },
    },
    {
      title: t('claudeCodeConfig.usageCacheHitRate'),
      key: 'cacheHitRate',
      width: 86,
      render: (_: unknown, row: { input: number; cacheRead: number }) => {
        const cacheable = row.input + row.cacheRead;
        return (
          <Text style={{ fontSize: 11 }}>
            {cacheable > 0 ? `${((row.cacheRead / cacheable) * 100).toFixed(1)}%` : '—'}
          </Text>
        );
      },
    },
    {
      title: t('claudeCodeConfig.usageColCost'),
      key: 'cost',
      width: 72,
      render: (_: unknown, row: { model: string; input: number; output: number; cacheRead: number; cacheCreation: number }) => {
        const cost = filteredRecords
          .filter((record) => record.model === row.model)
          .reduce((sum, record) => {
            const itemCost = calculateCost(
              record.model,
              record.inputTokens,
              record.outputTokens,
              record.cacheReadTokens,
              record.cacheCreationTokens,
              customPricing,
              {
                app: recordApp(record),
                reportedCostUsd: record.reportedCostUsd,
                cacheCreationLongTokens: record.cacheCreationLongTokens,
              }
            );
            return sum + (itemCost?.total ?? 0);
          }, 0);
        return <Text style={{ fontSize: 11 }}>{cost > 0 ? formatCost(cost) : '—'}</Text>;
      },
    },
  ];

  const modelData = Object.entries(activeAggregation.byModel)
    .map(([model, data]) => ({
      model,
      ...data,
      total: data.input + data.output + data.cacheRead + data.cacheCreation,
      key: model,
    }))
    .sort((a, b) => b.total - a.total);

  const updatePricingEntry = (
    key: string,
    field: 'inputPerMillion' | 'outputPerMillion' | 'cacheReadPerMillion' | 'cacheCreationPerMillion',
    value: number
  ) => {
    setEditingPricing((prev) => ({
      ...prev,
      [key]: { ...prev[key], [field]: value },
    }));
  };

  const updatePricingModelId = (oldKey: string, newKey: string) => {
    setEditingPricing((prev) => {
      const next: ModelPricingMap = {};
      for (const [k, v] of Object.entries(prev)) {
        next[k === oldKey ? newKey : k] = v;
      }
      return next;
    });
  };

  return (
    <div>
      {usageToolbar}
      {showProbeOnlyWarning ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message={t('claudeCodeConfig.usageProbeOnlyTitle')}
          description={t('claudeCodeConfig.usageProbeOnlyDesc', { count: probeCountInRange })}
        />
      ) : null}
      {showClaudeRouteWarning ? (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message={t('claudeCodeConfig.usageClaudeRouteOffTitle')}
          description={t('claudeCodeConfig.usageClaudeRouteOffDesc')}
        />
      ) : null}
      {rangeIsEmpty ? (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message={t('claudeCodeConfig.usageRangeEmpty')}
          action={(
            <Button size="small" onClick={() => setRangeFilter('all')}>
              {t('claudeCodeConfig.usageViewAll')}
            </Button>
          )}
        />
      ) : null}
      {visibleApps.length > 0 ? (
        <>
          <Segmented
            size="small"
            value={appFilter}
            onChange={(value) => setAppFilter(value as UsageAppFilter)}
            options={[
              ...(visibleApps.length > 1
                ? [{ label: t('claudeCodeConfig.usageFilterAll'), value: 'all' as const }]
                : []),
              ...visibleApps.map((app) => ({
                label: app === 'claude' ? 'Claude' : 'Codex',
                value: app,
              })),
            ]}
            style={{ marginBottom: 10 }}
          />

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))',
              gap: 8,
              marginBottom: 10,
            }}
          >
            {visibleApps.map((app) => {
              const stats = totalAggregation.byApp?.[app] ?? {
                input: 0,
                output: 0,
                cacheRead: 0,
                cacheCreation: 0,
                requests: 0,
              };
              const total = stats.input + stats.output + stats.cacheRead + stats.cacheCreation;
              return (
                <div
                  key={app}
                  style={{
                    padding: '9px 12px',
                    border: `1px solid ${appFilter === app ? palette.focusBorder : palette.panelBorder}`,
                    borderRadius: 8,
                    background: appFilter === app ? palette.codeBlockBackground : 'transparent',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: 10,
                    cursor: 'pointer',
                  }}
                  onClick={() => setAppFilter(appFilter === app ? (visibleApps.length > 1 ? 'all' : app) : app)}
                >
                  <Space size={6}>
                    <span
                      style={{
                        width: 8,
                        height: 8,
                        borderRadius: '50%',
                        background: app === 'claude' ? '#d97706' : '#1677ff',
                      }}
                    />
                    <Text strong style={{ fontSize: 12 }}>{app === 'claude' ? 'Claude' : 'Codex'}</Text>
                  </Space>
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    {stats.requests} {t('claudeCodeConfig.usageRequests')} · {formatTokenCount(total)} Token
                  </Text>
                </div>
              );
            })}
          </div>
        </>
      ) : null}

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(145px, 1fr))',
          gap: 8,
          marginBottom: 10,
        }}
      >
        {[
          {
            label: t('claudeCodeConfig.usageTotalRequests'),
            value: String(activeAggregation.totalRequests),
            detail: t('claudeCodeConfig.usageAvgTokens', { value: formatTokenCount(averageTokens) }),
            color: palette.editorForeground,
          },
          {
            label: t('claudeCodeConfig.usageTotalTokens'),
            value: formatTokenCount(activeAggregation.totalTokens),
            detail: t('claudeCodeConfig.usageOutputRatio', { value: outputRatio.toFixed(1) }),
            color: '#1677ff',
          },
          {
            label: t('claudeCodeConfig.usageCacheHitRate'),
            value: activeAggregation.totalCacheReadTokens > 0 ? `${activeAggregation.cacheHitRate.toFixed(1)}%` : '—',
            detail: `${t('claudeCodeConfig.usageCacheRead')} ${formatTokenCount(activeAggregation.totalCacheReadTokens)}`,
            color: '#722ed1',
          },
          {
            label: t('claudeCodeConfig.usageSuccessRate'),
            value: successRate != null ? `${successRate}%` : '—',
            detail: t('claudeCodeConfig.usageSuccessRateHint'),
            color: '#13c2c2',
          },
          {
            label: t('claudeCodeConfig.usageEstCost'),
            value: pricedRecords > 0 ? formatCost(totalCost) : '—',
            detail: pricedRecords === filteredRecords.length
              ? t('claudeCodeConfig.usagePricingComplete')
              : t('claudeCodeConfig.usagePricingCoverage', { priced: pricedRecords, total: filteredRecords.length }),
            color: '#fa8c16',
          },
        ].map((metric) => (
          <div
            key={metric.label}
            style={{
              padding: '12px 14px',
              border: `1px solid ${palette.panelBorder}`,
              borderRadius: 8,
              background: palette.codeBlockBackground,
              minWidth: 0,
            }}
          >
            <Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 5 }}>
              {metric.label}
            </Text>
            <div style={metricTone(metric.color)}>{metric.value}</div>
            <Text type="secondary" ellipsis style={{ fontSize: 10, display: 'block', marginTop: 5 }}>
              {metric.detail}
            </Text>
          </div>
        ))}
      </div>

      <div
        style={{
          padding: '12px 14px',
          border: `1px solid ${palette.panelBorder}`,
          borderRadius: 8,
          background: palette.codeBlockBackground,
          marginBottom: 14,
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, marginBottom: 9 }}>
          <Text strong style={{ fontSize: 12 }}>{t('claudeCodeConfig.usageTokenBreakdown')}</Text>
          {cacheSavings > 0.01 ? (
            <Text type="secondary" style={{ fontSize: 11 }}>
              {t('claudeCodeConfig.usageCacheSavings')}: {formatCost(cacheSavings)}
            </Text>
          ) : null}
        </div>
        <Text type="secondary" style={{ display: 'block', fontSize: 11, marginBottom: 8 }}>
          {t('claudeCodeConfig.usageCostIncludesCache')}
        </Text>
        <div
          style={{
            display: 'flex',
            overflow: 'hidden',
            height: 12,
            borderRadius: 6,
            background: palette.panelBorder,
            marginBottom: 9,
          }}
        >
          {tokenParts.map((part) => (
            <div
              key={part.id}
              title={`${part.label}: ${formatTokenCount(part.value)}`}
              style={{
                width: `${tokenPartsTotal > 0 ? (part.value / tokenPartsTotal) * 100 : 0}%`,
                minWidth: part.value > 0 ? 2 : 0,
                background: part.color,
              }}
            />
          ))}
        </div>
        <Space size={[14, 5]} wrap>
          {tokenParts.map((part) => (
            <Space key={part.id} size={5}>
              <span style={{ width: 8, height: 8, borderRadius: 2, background: part.color, display: 'inline-block' }} />
              <Text type="secondary" style={{ fontSize: 11 }}>
                {part.label} · {formatTokenCount(part.value)} · {((part.value / tokenPartsTotal) * 100).toFixed(1)}%
              </Text>
            </Space>
          ))}
        </Space>
      </div>

      <Segmented
        size="small"
        value={detailView}
        onChange={(value) => setDetailView(value as 'overview' | 'requests' | 'providers')}
        options={[
          { label: t('claudeCodeConfig.usageViewOverview'), value: 'overview' },
          { label: t('claudeCodeConfig.usageViewRequests'), value: 'requests' },
          { label: t('claudeCodeConfig.usageViewProviders'), value: 'providers' },
        ]}
        style={{ marginBottom: 12 }}
      />

      {detailView === 'overview' ? (
        <>
          {hasTrend ? (
            <div style={{ marginBottom: 14 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
                <Text strong style={{ fontSize: 12 }}>{t('claudeCodeConfig.usageTrendTitle')}</Text>
                <Segmented
                  size="small"
                  value={trendMetric}
                  onChange={(v) => setTrendMetric(v as UsageTrendMetric)}
                  options={[
                    { label: t('claudeCodeConfig.usageChartRequests'), value: 'requests' },
                    { label: t('claudeCodeConfig.usageChartTokens'), value: 'tokens' },
                    { label: t('claudeCodeConfig.usageChartCost'), value: 'cost', disabled: totalCost <= 0 },
                  ]}
                />
              </div>
              {trendMetric === 'requests' ? (
                <GatewayUsageChart
                  title={t('claudeCodeConfig.usageChartRequests')}
                  labels={labels}
                  series={requestsChart.series}
                  palette={palette}
                />
              ) : null}
              {trendMetric === 'tokens' ? (
                <GatewayUsageChart
                  title={t('claudeCodeConfig.usageChartTokens')}
                  labels={labels}
                  series={tokensChart.series}
                  palette={palette}
                  valueFormatter={formatTokenCount}
                />
              ) : null}
              {trendMetric === 'cost' && totalCost > 0 ? (
                <GatewayUsageChart
                  title={t('claudeCodeConfig.usageChartCost')}
                  labels={labels}
                  series={costChart.series}
                  palette={palette}
                  valueFormatter={formatChartCost}
                />
              ) : null}
            </div>
          ) : (
            <Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 12 }}>
              {t('claudeCodeConfig.usageTrendNeedMore')}
            </Text>
          )}

          <Text strong style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
            {t('claudeCodeConfig.usageByModel')}
          </Text>
          <Table
            size="small"
            pagination={modelData.length > 8 ? { pageSize: 8, size: 'small' } : false}
            dataSource={modelData}
            columns={modelColumns}
            style={{ marginBottom: 14 }}
          />
        </>
      ) : null}

      {detailView === 'requests' ? (
        <Table
          size="small"
          pagination={requestRows.length > 12 ? { pageSize: 12, size: 'small' } : false}
          dataSource={requestRows}
          scroll={{ x: 980 }}
          columns={[
            {
              title: t('claudeCodeConfig.usageColTime'),
              dataIndex: 'ts',
              width: 150,
              render: (ts: string) => (
                <Text style={{ fontSize: 11 }}>{new Date(ts).toLocaleString()}</Text>
              ),
            },
            {
              title: t('claudeCodeConfig.usageColProvider'),
              key: 'provider',
              width: 120,
              render: (_: unknown, row: TokenUsageRecord) => (
                <Text style={{ fontSize: 11 }}>{resolveRecordProvider(row)}</Text>
              ),
            },
            {
              title: t('claudeCodeConfig.usageColModel'),
              dataIndex: 'model',
              width: 140,
              render: (model: string, row: TokenUsageRecord) => (
                <Space size={4}>
                  <Text style={{ fontSize: 11 }}>{model}</Text>
                  {isProbeUsageRecord(row) ? (
                    <Text type="secondary" style={{ fontSize: 10 }}>
                      {t('claudeCodeConfig.usageProbeTag')}
                    </Text>
                  ) : null}
                </Space>
              ),
            },
            {
              title: t('claudeCodeConfig.usageColInput'),
              dataIndex: 'inputTokens',
              width: 80,
              render: (v: number) => <Text style={{ fontSize: 11 }}>{formatTokenCount(v)}</Text>,
            },
            {
              title: t('claudeCodeConfig.usageColOutput'),
              dataIndex: 'outputTokens',
              width: 80,
              render: (v: number) => <Text style={{ fontSize: 11 }}>{formatTokenCount(v)}</Text>,
            },
            {
              title: t('claudeCodeConfig.usageCacheRead'),
              dataIndex: 'cacheReadTokens',
              width: 80,
              render: (v: number) => <Text style={{ fontSize: 11 }}>{v > 0 ? formatTokenCount(v) : '—'}</Text>,
            },
            {
              title: t('claudeCodeConfig.usageColCost'),
              key: 'cost',
              width: 80,
              render: (_: unknown, row: TokenUsageRecord) => {
                const cost = calculateCost(
                  row.model,
                  row.inputTokens,
                  row.outputTokens,
                  row.cacheReadTokens,
                  row.cacheCreationTokens,
                  customPricing,
                  {
                    app: recordApp(row),
                    reportedCostUsd: row.reportedCostUsd,
                    cacheCreationLongTokens: row.cacheCreationLongTokens,
                  }
                );
                return <Text style={{ fontSize: 11 }}>{cost ? formatCost(cost.total) : '—'}</Text>;
              },
            },
            {
              title: t('claudeCodeConfig.usageColDuration'),
              dataIndex: 'durationMs',
              width: 90,
              render: (ms: number | undefined, row: TokenUsageRecord) => (
                <Text style={{ fontSize: 11 }}>
                  {typeof ms === 'number' ? `${(ms / 1000).toFixed(1)}s` : '—'}
                  {row.streaming ? ` · SSE` : ''}
                </Text>
              ),
            },
            {
              title: t('claudeCodeConfig.usageColStatus'),
              dataIndex: 'status',
              width: 70,
              render: (status: number | undefined) => (
                <Text style={{ fontSize: 11 }}>{typeof status === 'number' ? status : '—'}</Text>
              ),
            },
          ]}
          style={{ marginBottom: 14 }}
        />
      ) : null}

      {detailView === 'providers' ? (
        <Table
          size="small"
          pagination={providerRows.length > 8 ? { pageSize: 8, size: 'small' } : false}
          dataSource={providerRows.map((row) => ({ ...row, key: row.provider }))}
          columns={[
            {
              title: t('claudeCodeConfig.usageColProvider'),
              dataIndex: 'provider',
              render: (provider: string) => <Text style={{ fontSize: 11, fontWeight: 500 }}>{provider}</Text>,
            },
            {
              title: t('claudeCodeConfig.usageColRequests'),
              dataIndex: 'requests',
              width: 80,
            },
            {
              title: t('claudeCodeConfig.usageSuccessRate'),
              key: 'successRate',
              width: 90,
              render: (_: unknown, row: { requests: number; successes: number }) => (
                <Text style={{ fontSize: 11 }}>
                  {row.requests > 0 ? `${((row.successes / row.requests) * 100).toFixed(1)}%` : '—'}
                </Text>
              ),
            },
            {
              title: t('claudeCodeConfig.usageTotalTokens'),
              key: 'tokens',
              render: (_: unknown, row: { input: number; output: number; cacheRead: number; cacheCreation: number }) => (
                <Text style={{ fontSize: 11 }}>
                  {formatTokenCount(row.input + row.output + row.cacheRead + row.cacheCreation)}
                </Text>
              ),
            },
            {
              title: t('claudeCodeConfig.usageColInput'),
              dataIndex: 'input',
              width: 80,
              render: (v: number) => formatTokenCount(v),
            },
            {
              title: t('claudeCodeConfig.usageColOutput'),
              dataIndex: 'output',
              width: 80,
              render: (v: number) => formatTokenCount(v),
            },
          ]}
          style={{ marginBottom: 14 }}
        />
      ) : null}

      <Modal
        title={t('claudeCodeConfig.usagePricingTitle')}
        open={pricingModalOpen}
        onOk={() => { onSavePricing(editingPricing); setPricingModalOpen(false); }}
        onCancel={() => setPricingModalOpen(false)}
        width={820}
        okText={t('claudeCodeConfig.usagePricingSave')}
      >
        <Space style={{ marginBottom: 12, width: '100%', justifyContent: 'space-between' }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('claudeCodeConfig.usagePricingHint')}
          </Text>
          <Button size="small" icon={<ReloadOutlined />} onClick={() => {
            onRefreshPricing();
            setEditingPricing({ ...detectedPricing, ...customPricing });
          }}>
            {t('claudeCodeConfig.usagePricingRefresh')}
          </Button>
        </Space>
        {/* Column headers */}
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6, paddingLeft: 4 }}>
          <Text type="secondary" style={{ fontSize: 10, width: 160 }}>{t('claudeCodeConfig.usagePricingModel')}</Text>
          <Text type="secondary" style={{ fontSize: 10, width: 88 }}>{t('claudeCodeConfig.usagePricingInput')}</Text>
          <Text type="secondary" style={{ fontSize: 10, width: 88 }}>{t('claudeCodeConfig.usagePricingOutput')}</Text>
          <Text type="secondary" style={{ fontSize: 10, width: 88 }}>{t('claudeCodeConfig.usagePricingCacheRead')}</Text>
          <Text type="secondary" style={{ fontSize: 10, width: 88 }}>{t('claudeCodeConfig.usagePricingCacheCreation')}</Text>
          <Text type="secondary" style={{ fontSize: 10, width: 88 }}>{t('claudeCodeConfig.usagePricingCacheCreationLong')}</Text>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {Object.entries(editingPricing).map(([modelId, price]) => (
            <div key={modelId} style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <Input
                value={modelId}
                onChange={(e) => updatePricingModelId(modelId, e.target.value)}
                style={{ width: 160, fontSize: 12 }}
              />
              <InputNumber
                value={price.inputPerMillion}
                onChange={(v) => updatePricingEntry(modelId, 'inputPerMillion', v ?? 0)}
                style={{ width: 88 }}
                min={0}
                step={0.01}
                placeholder="Input"
              />
              <InputNumber
                value={price.outputPerMillion}
                onChange={(v) => updatePricingEntry(modelId, 'outputPerMillion', v ?? 0)}
                style={{ width: 88 }}
                min={0}
                step={0.01}
                placeholder="Output"
              />
              <InputNumber
                value={price.cacheReadPerMillion ?? 0}
                onChange={(v) => updatePricingEntry(modelId, 'cacheReadPerMillion', v ?? 0)}
                style={{ width: 88 }}
                min={0}
                step={0.01}
                placeholder="Cache read"
              />
              <InputNumber
                value={price.cacheCreationPerMillion ?? 0}
                onChange={(v) => updatePricingEntry(modelId, 'cacheCreationPerMillion', v ?? 0)}
                style={{ width: 88 }}
                min={0}
                step={0.01}
                placeholder="Cache write"
              />
              <InputNumber
                value={price.cacheCreationLongPerMillion ?? price.cacheCreationPerMillion ?? 0}
                onChange={(v) => updatePricingEntry(modelId, 'cacheCreationLongPerMillion', v ?? 0)}
                style={{ width: 88 }}
                min={0}
                step={0.01}
                placeholder="Long cache"
              />
              <Button size="small" danger icon={<DeleteOutlined />} onClick={() => {
                setEditingPricing((prev) => {
                  const next = { ...prev };
                  delete next[modelId];
                  return next;
                });
              }} />
            </div>
          ))}
        </div>
        <Space style={{ marginTop: 12 }}>
          <Button size="small" onClick={() => {
            setEditingPricing((prev) => ({
              ...prev,
              [`custom_${Date.now()}`]: { inputPerMillion: 0, outputPerMillion: 0 },
            }));
          }}>
            {t('claudeCodeConfig.usagePricingAdd')}
          </Button>
          <Button size="small" onClick={() => {
            onClearPricing();
            setEditingPricing(detectedPricing);
          }}>
            {t('claudeCodeConfig.usagePricingReset')}
          </Button>
        </Space>
      </Modal>
    </div>
  );
}
