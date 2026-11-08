export type GatewayRuntimeStats = {
  startedAt: string;
  uptimeMs: number;
  totalRequests: number;
  successfulRequests: number;
  failedRequests: number;
  activeConnections: number;
  successRate: number;
  /** 可选限额(借鉴 CCR 访问控制):0/未设=不限制。 */
  maxRequests?: number;
  limitReached?: boolean;
};

export class GatewayRuntimeStatsTracker {
  private startedAt = Date.now();
  private totalRequests = 0;
  private successfulRequests = 0;
  private failedRequests = 0;
  private activeConnections = 0;
  private maxRequests: number;

  constructor() {
    // AGENTSOCIETY_GATEWAY_MAX_REQUESTS:本次网关会话的请求上限;
    // 未设或 ≤0 不限制。防 CLI 失控循环烧钱(借鉴 CCR 限额控制)。
    const raw = Number(process.env.AGENTSOCIETY_GATEWAY_MAX_REQUESTS ?? '0');
    this.maxRequests = Number.isFinite(raw) && raw > 0 ? Math.floor(raw) : 0;
  }

  reset(): void {
    this.startedAt = Date.now();
    this.totalRequests = 0;
    this.successfulRequests = 0;
    this.failedRequests = 0;
    this.activeConnections = 0;
  }

  /** 是否已超请求限额(超限时网关以 429 拒绝新请求)。 */
  limitReached(): boolean {
    return this.maxRequests > 0 && this.totalRequests >= this.maxRequests;
  }

  onRequestStart(): void {
    this.totalRequests += 1;
    this.activeConnections += 1;
  }

  onRequestEnd(success: boolean): void {
    this.activeConnections = Math.max(0, this.activeConnections - 1);
    if (success) {
      this.successfulRequests += 1;
    } else {
      this.failedRequests += 1;
    }
  }

  snapshot(now = Date.now()): GatewayRuntimeStats {
    const total = this.totalRequests;
    const successRate = total > 0 ? Math.round((this.successfulRequests / total) * 1000) / 10 : 100;
    return {
      startedAt: new Date(this.startedAt).toISOString(),
      uptimeMs: Math.max(0, now - this.startedAt),
      totalRequests: total,
      successfulRequests: this.successfulRequests,
      failedRequests: this.failedRequests,
      activeConnections: this.activeConnections,
      successRate,
      maxRequests: this.maxRequests > 0 ? this.maxRequests : undefined,
      limitReached: this.limitReached(),
    };
  }
}
