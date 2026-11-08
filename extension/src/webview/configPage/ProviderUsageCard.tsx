import * as React from 'react';
import { Button, Progress, Space, Tag, Tooltip, Typography } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import type { ProviderUsageResult } from '../../shared/providerUsage';
import type { VscodeThemePalette } from '../theme';

const { Text } = Typography;

export function ProviderUsageCard({ usage, palette, onRefresh }: {
  usage?: ProviderUsageResult & { loading?: boolean };
  palette: VscodeThemePalette;
  onRefresh?: () => void;
}) {
  const { t, i18n } = useTranslation();
  const date = (value: string) => new Date(value).toLocaleString(i18n.language, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
  const scope = usage?.scope;
  const errorKey = `claudeCodeConfig.providerUsageErrors.${usage?.error}`;
  const errorText = usage?.error
    ? t(errorKey, { defaultValue: t('claudeCodeConfig.providerUsageErrors.query_failed') }) : '';
  return (
    <section aria-label={t('claudeCodeConfig.accountUsage.title')} style={{ marginTop: 12, paddingTop: 10, borderTop: `1px solid ${palette.panelBorder}`, minWidth: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
        <Space size={6} wrap>
          <Text type="secondary" style={{ fontSize: 12 }}>{t(`claudeCodeConfig.accountUsage.${scope ?? 'title'}`)}</Text>
          {usage?.available === false ? <Tag color="warning">{t('claudeCodeConfig.accountUsage.unavailable')}</Tag> : null}
        </Space>
        <Button size="small" type="text" icon={<ReloadOutlined aria-hidden="true" />} loading={usage?.loading} onClick={onRefresh} disabled={!onRefresh}>
          {t('claudeCodeConfig.providerQueryQuota')}
        </Button>
      </div>
      {usage?.plans?.length ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 210px), 1fr))', gap: 12, marginTop: 8 }}>
          {usage.plans.map((plan, index) => {
            const low = plan.remainingPercent !== undefined && plan.remainingPercent < 10;
            const color = low ? palette.warningForeground : palette.linkForeground;
            const withUnit = (value: string) => {
              if (!plan.unit || value.includes(plan.unit) || (plan.unit === 'USD' && value.startsWith('$')) || value === '—') { return value; }
              return plan.unit === '%' ? `${value}%` : `${value} ${plan.unit}`;
            };
            return (
              <div key={`${plan.name}-${index}`} style={{ minWidth: 0 }}>
                {plan.name ? <Text type="secondary" style={{ fontSize: 12 }}>{plan.name}</Text> : null}
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap', alignItems: 'baseline' }}>
                  <Text strong style={{ fontSize: 18, color }}>{withUnit(plan.remaining)}</Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>{t('claudeCodeConfig.accountUsage.remaining')}</Text>
                </div>
                {plan.remainingPercent !== undefined ? (
                  <Progress percent={plan.remainingPercent} showInfo={false} size="small" strokeColor={color} aria-label={t('claudeCodeConfig.accountUsage.remaining')} />
                ) : null}
                <Space size={[12, 2]} wrap>
                  {plan.used !== undefined ? <Text type="secondary" style={{ fontSize: 12 }}>{t('claudeCodeConfig.accountUsage.used', { value: withUnit(plan.used) })}</Text> : null}
                  {plan.total !== undefined ? <Text type="secondary" style={{ fontSize: 12 }}>{t('claudeCodeConfig.accountUsage.total', { value: withUnit(plan.total) })}</Text> : null}
                  {plan.details?.map((detail) => <Text key={detail.label} type="secondary" style={{ fontSize: 12 }}>{t(`claudeCodeConfig.accountUsage.${detail.label}`)} {withUnit(detail.value)}</Text>)}
                </Space>
                {plan.resetsAt ? <Text type="secondary" style={{ display: 'block', fontSize: 12 }}>{t('claudeCodeConfig.accountUsage.resetsAt', { value: date(plan.resetsAt) })}</Text> : null}
              </div>
            );
          })}
        </div>
      ) : errorText ? null : <Text type="secondary" style={{ fontSize: 12 }}>{t(usage?.loading ? 'claudeCodeConfig.providerQuotaLoading' : 'claudeCodeConfig.accountUsage.notQueried')}</Text>}
      {errorText ? <Text type="warning" role="status" style={{ display: 'block', marginTop: 6, fontSize: 12 }}>{errorText}</Text> : null}
      {usage?.fetchedAt ? (
        <Tooltip title={t('claudeCodeConfig.accountUsage.sourceHint')}>
          <Text type="secondary" style={{ display: 'block', marginTop: 6, fontSize: 11 }}>
            {t(usage.ok ? 'claudeCodeConfig.accountUsage.updated' : 'claudeCodeConfig.accountUsage.lastSuccess', { value: date(usage.fetchedAt) })}
          </Text>
        </Tooltip>
      ) : null}
    </section>
  );
}
