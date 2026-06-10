import { useCallback, useState } from 'react';

import { useStore } from '../data/store';
import { hasProAccess, type ProGateIntent } from '../lib/proAccess';

export function useProPaywall() {
  const pro = useStore((s) => s.prefs.rateIntelligencePro);
  const [gate, setGate] = useState<{ visible: boolean; intent: ProGateIntent }>({
    visible: false,
    intent: 'alert_limit',
  });

  const requestPro = useCallback(
    (intent: ProGateIntent): boolean => {
      if (hasProAccess({ rateIntelligencePro: pro })) return true;
      setGate({ visible: true, intent });
      return false;
    },
    [pro],
  );

  const closePaywall = useCallback(() => {
    setGate((g) => ({ ...g, visible: false }));
  }, []);

  return {
    pro,
    paywallVisible: gate.visible,
    paywallIntent: gate.intent,
    requestPro,
    closePaywall,
  };
}
