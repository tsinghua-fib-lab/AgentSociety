/**
 * Agent avatar icons - imported from V1 frontend assets
 * These will be inlined as data URLs by webpack
 */

// @ts-ignore - PNG imports handled by webpack
import agentIcon from '../../../media/icons/agent.png';
// @ts-ignore
import boy1Icon from '../../../media/icons/boy1.png';
// @ts-ignore
import boy2Icon from '../../../media/icons/boy2.png';
// @ts-ignore
import boy3Icon from '../../../media/icons/boy3.png';
// @ts-ignore
import girl1Icon from '../../../media/icons/girl1.png';
// @ts-ignore
import girl2Icon from '../../../media/icons/girl2.png';
// @ts-ignore
import girl3Icon from '../../../media/icons/girl3.png';
// @ts-ignore - Panel section icons
import infoIcon from '../../../media/icons/info.png';
// @ts-ignore
import statusIcon from '../../../media/icons/status.png';
// @ts-ignore
import historyIcon from '../../../media/icons/history.png';

export const AGENT_ICONS = {
  agent: agentIcon as string,
  boy1: boy1Icon as string,
  boy2: boy2Icon as string,
  boy3: boy3Icon as string,
  girl1: girl1Icon as string,
  girl2: girl2Icon as string,
  girl3: girl3Icon as string,
};

// Panel section icons
export const PANEL_ICONS = {
  info: infoIcon as string,
  status: statusIcon as string,
  history: historyIcon as string,
};

/**
 * Get avatar icon URL based on agent profile (gender + age)
 */
export function getAgentIconUrl(profile: Record<string, any> | undefined): string {
  const age = profile?.age;
  const gender = typeof profile?.gender === 'string' ? profile.gender.toLowerCase() : '';
  if (typeof age === 'number' && gender === 'male') {
    if (age < 18) { return AGENT_ICONS.boy1; }
    return age < 65 ? AGENT_ICONS.boy2 : AGENT_ICONS.boy3;
  }
  if (typeof age === 'number' && gender === 'female') {
    if (age < 18) { return AGENT_ICONS.girl1; }
    return age < 65 ? AGENT_ICONS.girl2 : AGENT_ICONS.girl3;
  }
  return AGENT_ICONS.agent;
}
