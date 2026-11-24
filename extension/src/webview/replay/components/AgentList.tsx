/**
 * Agent List Component
 * Displays list of agents with their current status
 */

import * as React from 'react';
import { useTranslation } from 'react-i18next';
import { useReplay } from '../store';

export const AgentList: React.FC = () => {
  const { t } = useTranslation();
  const { state, actions } = useReplay();
  const { agentProfiles, agentStateRowsAtStep, selectedAgentId, panelSchema } = state;
  const primaryDatasetId = panelSchema?.primary_agent_state_dataset_id ?? null;
  const primaryRows = primaryDatasetId ? agentStateRowsAtStep[primaryDatasetId]?.rows_by_agent_id ?? {} : {};

  // Sort agents by ID
  const sortedAgents = React.useMemo(() => {
    return Array.from(agentProfiles.values()).sort((a, b) => a.id - b.id);
  }, [agentProfiles]);

  const handleAgentClick = (agentId: number) => {
    actions.selectAgent(agentId === selectedAgentId ? null : agentId);
  };

  return (
    <div className="agent-list">
      {sortedAgents.map((agent) => {
        const status = primaryRows[String(agent.id)] ?? null;
        const isSelected = agent.id === selectedAgentId;

        // Get initials for avatar
        const initials = agent.name
          .split(' ')
          .map((n) => n[0])
          .join('')
          .slice(0, 2)
          .toUpperCase();

        return (
          <div
            key={agent.id}
            className={`agent-item ${isSelected ? 'selected' : ''}`}
            onClick={() => handleAgentClick(agent.id)}
          >
            <div className="agent-avatar">{initials}</div>
            <div className="agent-info">
              <div className="agent-name">{agent.name}</div>
              <div className="agent-action">
                {status?.action || status?.thought || status?.t || t('replay.rows.noActivity')}
              </div>
            </div>
          </div>
        );
      })}

      {sortedAgents.length === 0 && (
        <div style={{ padding: '16px', textAlign: 'center', color: 'var(--vscode-descriptionForeground)' }}>
          {t('replay.rows.empty')}
        </div>
      )}
    </div>
  );
};
