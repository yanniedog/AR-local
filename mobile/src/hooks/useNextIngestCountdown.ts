import { useEffect, useState } from 'react';

import { getNextIngestCountdown, type IngestCountdownSnapshot } from '../lib/nextIngest';

export function useNextIngestCountdown(intervalMs = 1000): IngestCountdownSnapshot {
  const [snapshot, setSnapshot] = useState(() => getNextIngestCountdown(Date.now()));

  useEffect(() => {
    let nextDueMs = snapshot.nextDueMs;
    const tick = () => {
      const now = Date.now();
      if (now >= nextDueMs) {
        const fresh = getNextIngestCountdown(now);
        nextDueMs = fresh.nextDueMs;
        setSnapshot(fresh);
      } else {
        setSnapshot(getNextIngestCountdown(now, nextDueMs));
      }
    };
    tick();
    const id = setInterval(tick, intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);

  return snapshot;
}
