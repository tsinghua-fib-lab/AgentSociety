/**
 * Left-side agent information and per-agent state panel
 */

import * as React from 'react';
import { useTranslation } from 'react-i18next';
import { Button, Divider, Empty, Flex, Modal, Pagination, Select, Spin, Table, Tooltip, Typography } from 'antd';
import { CloseOutlined, DatabaseOutlined, ReloadOutlined } from '@ant-design/icons';
import { useReplay } from '../store';
import type { ReplayDatasetColumn, ReplayDatasetInfo } from '../types';
import { PANEL_ICONS } from '../icons';

const { Title } = Typography;
const AGENT_HISTORY_REQUEST_KEY = 'agent-history-raw-table';
const HISTORY_PAGE_SIZE = 20;

function formatValue(value: any): React.ReactNode {
  if (value === null || value === undefined) {
    return <span style={{ color: 'var(--as-muted-text)' }}>-</span>;
  }
  if (typeof value === 'object') {
    return (
      <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: '11px' }}>
        {JSON.stringify(value, null, 2)}
      </pre>
    );
  }
  return String(value);
}

function getColumnLabel(columns: ReplayDatasetColumn[], key: string): string {
  return columns.find((column) => column.column_name === key)?.title || key;
}

const DatasetRowCard: React.FC<{
  dataset: ReplayDatasetInfo;
  row: Record<string, any> | null | undefined;
}> = ({ dataset, row }) => {
  const { t } = useTranslation();
  if (!row) {
    return (
      <div className="left-info-history-card" style={{ marginTop: '8px' }}>
        <div className="left-info-history-inner" style={{ color: 'var(--as-muted-text)' }}>
          {t('replay.rows.noCurrent')}
        </div>
      </div>
    );
  }

  const entries = Object.entries(row).filter(([key]) => !['agent_id'].includes(key));

  return (
    <div className="left-info-history-card" style={{ marginTop: '8px' }}>
      <div className="left-info-history-inner">
        <div style={{ fontWeight: 600, color: 'var(--as-accent-text)', marginBottom: '8px' }}>
          {dataset.title || dataset.dataset_id}
        </div>
        <div style={{ fontSize: '11px', color: 'var(--as-muted-text)', marginBottom: '8px' }}>
          {dataset.module_name} / {dataset.dataset_id}
        </div>
        <Flex vertical gap={8}>
          {entries.map(([key, value]) => (
            <div key={key}>
              <div style={{ fontSize: '11px', color: 'var(--as-muted-text)', marginBottom: '2px' }}>
                {getColumnLabel(dataset.columns, key)}
              </div>
              <div style={{ color: 'var(--as-strong-text)' }}>{formatValue(value)}</div>
            </div>
          ))}
        </Flex>
      </div>
    </div>
  );
};

export const AgentDetailPanel: React.FC = () => {
  const { t } = useTranslation();
  const { state, actions, sendMessage } = useReplay();
  const {
    selectedAgentId,
    agentProfiles,
    panelSchema,
    agentStateRowsAtStep,
    selectedAgentHistoryDatasetId,
    replayDatasetRowsByRequestKey,
    timeline,
    currentStep,
  } = state;

  const profile = agentProfiles.get(selectedAgentId ?? -1);
  const currentStepNumber = timeline[currentStep]?.step ?? null;
  const agentStateDatasets = panelSchema?.agent_state_datasets ?? [];
  const datasetMap = React.useMemo(
    () => new Map(agentStateDatasets.map((dataset) => [dataset.dataset_id, dataset])),
    [agentStateDatasets]
  );
  const historyDatasetId = selectedAgentHistoryDatasetId || panelSchema?.primary_agent_state_dataset_id || null;
  const historyDataset = historyDatasetId ? datasetMap.get(historyDatasetId) ?? null : null;
  const historyTableRows = replayDatasetRowsByRequestKey[AGENT_HISTORY_REQUEST_KEY] ?? null;
  const [historyPage, setHistoryPage] = React.useState(1);
  const [historyLoading, setHistoryLoading] = React.useState(false);
  const [historyModalOpen, setHistoryModalOpen] = React.useState(false);
  const currentRows = selectedAgentId === null
    ? []
    : agentStateDatasets.map((dataset) => ({
      dataset,
      row: agentStateRowsAtStep[dataset.dataset_id]?.rows_by_agent_id[String(selectedAgentId)] ?? null,
    }));

  React.useEffect(() => {
    setHistoryPage(1);
    setHistoryModalOpen(false);
    setHistoryLoading(false);
    actions.setReplayDatasetRows(AGENT_HISTORY_REQUEST_KEY, null);
  }, [actions, selectedAgentId, historyDatasetId]);

  const openHistoryRawTable = React.useCallback((page: number = 1) => {
    if (selectedAgentId === null || !historyDataset) {
      return;
    }
    setHistoryPage(page);
    setHistoryModalOpen(true);
    setHistoryLoading(true);
    actions.setReplayDatasetRows(AGENT_HISTORY_REQUEST_KEY, null);
    sendMessage({
      command: 'fetchReplayDatasetRows',
      requestKey: AGENT_HISTORY_REQUEST_KEY,
      datasetId: historyDataset.dataset_id,
      page,
      pageSize: HISTORY_PAGE_SIZE,
      entityId: selectedAgentId,
      endStep: currentStepNumber ?? undefined,
      descOrder: true,
    });
  }, [actions, currentStepNumber, historyDataset, selectedAgentId, sendMessage]);

  React.useEffect(() => {
    if (!historyDataset || !historyTableRows || historyTableRows.dataset_id !== historyDataset.dataset_id) {
      return;
    }
    setHistoryLoading(false);
  }, [historyDataset, historyTableRows]);

  const historyColumns = React.useMemo(() => {
    if (!historyDataset || !historyTableRows) {
      return [];
    }
    return historyTableRows.columns.map((column) => ({
      title: getColumnLabel(historyDataset.columns, column),
      dataIndex: column,
      key: column,
      render: (value: any) => formatValue(value),
      ellipsis: true,
      width: ['step', 'agent_id', 't'].includes(column) ? 140 : 180,
    }));
  }, [historyDataset, historyTableRows]);

  const rootClass = profile ? 'left-inner' : 'left-inner collapsed';
  const profileEntries = React.useMemo(
    () => Object.entries(profile?.profile ?? {}).filter(([key]) => key !== 'name'),
    [profile]
  );

  return (
    <Flex vertical justify="flex-start" align="center" className={rootClass}>
      <Flex gap="small" align="center" style={{ marginTop: '8px', width: '100%' }}>
        <img src={PANEL_ICONS.info} width="32" height="32" alt="info" />
        <Title level={4} style={{ margin: 0, flex: 1 }}>{t('replay.left.agentInfo')}</Title>
        <Button
          shape="circle"
          icon={<CloseOutlined />}
          size="small"
          type="text"
          onClick={() => actions.selectAgent(null)}
        />
      </Flex>

      {profile ? (
        <>
          <Flex wrap justify="left" style={{ width: '100%', marginTop: '8px' }}>
            <Flex className="left-info-block" justify="space-between">
              <span style={{ fontWeight: 400, color: 'var(--as-muted-text)' }}>{t('replay.left.name')}  </span>
              <Tooltip title={<span>ID = {profile.id}</span>}>
                <span style={{ fontWeight: 600, color: 'var(--as-accent-text)' }}>{profile.name}</span>
              </Tooltip>
            </Flex>
            {profileEntries.map(([key, value]) => (
              <Flex
                className={typeof value === 'object' ? 'left-info-block-status' : 'left-info-block'}
                justify="space-between"
                key={key}
              >
                <span style={{ fontWeight: 400, color: 'var(--as-muted-text)' }}>{key}:&nbsp;&nbsp;</span>
                <div style={{ fontWeight: 600, color: 'var(--as-accent-text)', maxWidth: '72%', overflow: 'hidden' }}>
                  {formatValue(value)}
                </div>
              </Flex>
            ))}
          </Flex>

          <Divider style={{ margin: '12px 0' }} />

          <Flex gap="small" align="center" style={{ width: '100%' }}>
            <img src={PANEL_ICONS.status} width="32" height="32" alt="status" />
            <Title level={4} style={{ margin: 0 }}>{t('replay.rows.current')}</Title>
          </Flex>

          <div style={{ width: '100%', marginTop: '8px' }}>
            {currentRows.length === 0 ? (
              <div className="left-info-empty">{t('replay.rows.noStates')}</div>
            ) : (
              currentRows.map(({ dataset, row }) => (
                <DatasetRowCard key={dataset.dataset_id} dataset={dataset} row={row} />
              ))
            )}
          </div>

          <Divider style={{ margin: '12px 0' }} />

          <Flex gap="small" align="center" style={{ width: '100%' }}>
            <img src={PANEL_ICONS.history} width="32" height="32" alt="history" />
            <Title level={4} style={{ margin: 0, flex: 1 }}>{t('replay.rows.history')}</Title>
          </Flex>

          {agentStateDatasets.length > 0 && (
            <Select
              style={{ width: '100%', marginTop: '8px' }}
              value={historyDatasetId ?? undefined}
              options={agentStateDatasets.map((dataset) => ({
                value: dataset.dataset_id,
                label: dataset.title || dataset.dataset_id,
              }))}
              onChange={(value) => actions.setSelectedAgentHistoryDatasetId(value)}
            />
          )}

          <Flex vertical className="w-full" style={{ marginTop: '8px', minHeight: '48px', width: '100%' }}>
            {!historyDataset ? (
              <div className="left-info-empty">{t('replay.rows.noHistory')}</div>
            ) : (
              <div
                className="left-info-history-card"
                style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: '12px' }}
              >
                <div className="left-info-history-inner" style={{ width: '100%' }}>
                  <Flex align="center" justify="space-between" style={{ marginBottom: '8px' }}>
                    <div>
                      <div style={{ fontWeight: 600, color: 'var(--as-accent-text)' }}>
                        {historyDataset.title || historyDataset.dataset_id}
                      </div>
                      <div style={{ fontSize: '11px', color: 'var(--as-muted-text)', marginTop: '4px' }}>
                        {historyDataset.module_name} / {historyDataset.dataset_id}
                      </div>
                    </div>
                    <Button
                      size="small"
                      icon={<DatabaseOutlined />}
                      onClick={() => openHistoryRawTable(1)}
                    >
                      {t('replay.rows.raw')}
                    </Button>
                  </Flex>

                  {historyDataset.description ? (
                    <div style={{ fontSize: '12px', color: 'var(--vscode-descriptionForeground)', marginBottom: '8px' }}>
                      {historyDataset.description}
                    </div>
                  ) : null}

                  <div style={{ fontSize: '11px', color: 'var(--as-muted-text)' }}>
                    {t('replay.rows.agentId', { id: selectedAgentId })} · {currentStepNumber !== null ? t('replay.rows.upToStep', { step: currentStepNumber }) : t('replay.rows.all')}
                  </div>
                </div>
              </div>
            )}
          </Flex>

          <Modal
            title={historyDataset ? `${t('replay.rows.history')} · ${historyDataset.title || historyDataset.dataset_id}` : t('replay.rows.history')}
            open={historyModalOpen}
            onCancel={() => setHistoryModalOpen(false)}
            footer={null}
            width={1000}
            style={{ top: 20 }}
          >
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {historyDataset && historyTableRows?.dataset_id === historyDataset.dataset_id ? (
                historyTableRows.rows.length === 0 ? (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description={t('replay.rows.noAgentRows')}
                  />
                ) : (
                  <>
                    <Table
                      dataSource={historyTableRows.rows}
                      columns={historyColumns}
                      size="small"
                      pagination={false}
                      bordered
                      scroll={{ x: 'max-content', y: 560 }}
                      rowKey={(_, index) => `${historyDataset.dataset_id}-${historyPage}-${index ?? 0}`}
                      onRow={(record) => {
                        const isCurrentStep = currentStepNumber !== null && Number(record.step) === currentStepNumber;
                        return isCurrentStep
                          ? {
                            style: {
                              background: 'var(--vscode-list-activeSelectionBackground)',
                            },
                          }
                          : {};
                      }}
                    />
                    <Flex justify="space-between" align="center">
                      <Button
                        icon={<ReloadOutlined />}
                        onClick={() => openHistoryRawTable(historyPage)}
                      >
                        {t('replay.timeline.refresh')}
                      </Button>
                      <Flex align="center" gap={12}>
                        <span style={{ fontSize: '11px', color: 'var(--as-muted-text)' }}>
                          Showing raw rows filtered by `agent_id = {selectedAgentId}`{currentStepNumber !== null ? ` and step <= ${currentStepNumber}` : ''}
                        </span>
                        <Pagination
                          simple
                          current={historyPage}
                          total={historyTableRows.total}
                          pageSize={HISTORY_PAGE_SIZE}
                          onChange={(page) => openHistoryRawTable(page)}
                          size="small"
                        />
                      </Flex>
                    </Flex>
                  </>
                )
              ) : (
                <div style={{ textAlign: 'center', padding: 40 }}>
                  {historyLoading ? <Spin tip={t('replay.rows.loading')} /> : t('replay.rows.waiting')}
                </div>
              )}
            </div>
          </Modal>
        </>
      ) : (
        <div className="left-info-empty" style={{ marginTop: '20px', color: 'var(--as-muted-text)' }}>
          {t('replay.left.selectAgent')}
        </div>
      )}
    </Flex>
  );
};
