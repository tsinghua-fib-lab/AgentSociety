import type { AiCliGatewayUpstream } from './aiCliGatewayUpstream';

export const FAILOVER_FAILURE_THRESHOLD = 3;
export const FAILOVER_COOLDOWN_MS = 60_000;
export const FAILOVER_MAX_ATTEMPTS = 6;

export type CircuitBreakerState = {
  consecutiveFailures: number;
  openUntil: number;
  /** 半开探测(借鉴 cc-switch/CCR):冷却到期后不直接全量恢复,先放行
   * 一个试探请求;失败立即重新熔断,成功才清零。防止冷却期一过就
   * 把全部流量砸向尚未恢复的上游。 */
  halfOpen?: boolean;
};

export function shouldFailoverHttpStatus(status: number): boolean {
  return status === 0 || status === 408 || status === 429 || status >= 500;
}

export function isCircuitOpen(state: CircuitBreakerState | undefined, now = Date.now()): boolean {
  if (!state) {
    return false;
  }
  if (state.halfOpen || state.openUntil > now) {
    return true;
  }
  return false;
}

/**
 * 冷却到期后该上游是否处于半开态(应放行试探请求)。
 * 到期且曾有熔断记录 → 半开;从未熔断 → false(正常放行)。
 */
export function isHalfOpen(state: CircuitBreakerState | undefined, now = Date.now()): boolean {
  if (!state || state.consecutiveFailures < FAILOVER_FAILURE_THRESHOLD) {
    return false;
  }
  return state.openUntil <= now;
}

export function recordUpstreamFailure(
  map: Map<string, CircuitBreakerState>,
  baseUrl: string,
  now = Date.now()
): void {
  const key = baseUrl.trim();
  const prev = map.get(key) ?? { consecutiveFailures: 0, openUntil: 0 };
  if (prev.halfOpen) {
    // 半开试探失败:立即重新熔断(无需再数满阈值)。
    map.set(key, {
      consecutiveFailures: Math.max(prev.consecutiveFailures, FAILOVER_FAILURE_THRESHOLD),
      openUntil: now + FAILOVER_COOLDOWN_MS,
      halfOpen: false,
    });
    return;
  }
  const consecutiveFailures = prev.consecutiveFailures + 1;
  const openUntil =
    consecutiveFailures >= FAILOVER_FAILURE_THRESHOLD
      ? now + FAILOVER_COOLDOWN_MS
      : prev.openUntil;
  map.set(key, { consecutiveFailures, openUntil });
}

export function recordUpstreamSuccess(map: Map<string, CircuitBreakerState>, baseUrl: string): void {
  map.delete(baseUrl.trim());
}

export type CircuitBreakerHealth = 'healthy' | 'degraded' | 'unhealthy';

export function upstreamHealth(state: CircuitBreakerState | undefined): CircuitBreakerHealth {
  if (!state || state.consecutiveFailures === 0) {
    return 'healthy';
  }
  if (state.consecutiveFailures >= FAILOVER_FAILURE_THRESHOLD) {
    return 'unhealthy';
  }
  return 'degraded';
}

export function buildFailoverUpstreamOrder(
  upstreams: AiCliGatewayUpstream[],
  activeBaseUrl: string
): AiCliGatewayUpstream[] {
  const active = activeBaseUrl.trim();
  const seen = new Set<string>();
  const ordered: AiCliGatewayUpstream[] = [];
  for (const u of upstreams) {
    const key = `${u.baseUrl.trim()}|${u.apiKey.trim()}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    if (u.baseUrl.trim() === active) {
      ordered.unshift(u);
    } else {
      ordered.push(u);
    }
  }
  if (ordered.length === 0 && upstreams.length > 0) {
    return upstreams;
  }
  return ordered;
}
