export type LimitWindowKind = 'five_hour' | 'seven_day';

export type AccountLimitWindow = {
  kind: LimitWindowKind | string;
  used_percent: number;
  resets_at: number | string;
  captured_at?: string;
  stale?: boolean;
};

export type AccountLimits = {
  account_id: string;
  account_name?: string | null;
  engine?: string | null;
  windows: AccountLimitWindow[];
  captured_at?: string;
  stale?: boolean;
  status?: string | null;
};

export type LimitsResponse = AccountLimits[] | { accounts?: AccountLimits[]; limits?: AccountLimits[] };

/** The API reports capture time per window; the card shows the freshest one. */
export function accountCapturedAt(account: AccountLimits): Date | null {
  const times = [account.captured_at, ...account.windows.map((item) => item.captured_at)]
    .filter((value): value is string => Boolean(value))
    .map((value) => new Date(value))
    .filter((date) => !Number.isNaN(date.getTime()));
  return times.length ? new Date(Math.max(...times.map((date) => date.getTime()))) : null;
}

export function accountStale(account: AccountLimits): boolean {
  return Boolean(account.stale ?? (account.windows.length > 0 && account.windows.every((item) => item.stale)));
}
