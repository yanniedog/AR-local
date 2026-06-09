import { useEffect, useState } from 'react';

import { getNextIngestCountdown, type IngestCountdownSnapshot } from '../lib/nextIngest';

export function useNextIngestCountdown(intervalMs = 1000): IngestCountdownSnapshot {
  const [snapshot, setSnapshot] = useState(() => getNextIngestCountdown(Date.now()));

  useEffect(() => {
    const tick = () => {
      setSnapshot((prev) => {
        const now = Date.now();
        if (now >= prev.nextDueMs) {
          return getNextIngestCountdown(now);
        }
        return getNextIngestCountdown(now, prev.nextDueMs);
      });
    };
    const id = setInterval(tick, intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);

  return snapshot;
}