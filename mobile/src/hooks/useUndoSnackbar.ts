import { useCallback, useEffect, useRef, useState } from 'react';

export type UndoSnack = {
  message: string;
  onUndo: () => void;
};

export const UNDO_SNACKBAR_MS = 5000;

/** Brief undo snackbar with auto-dismiss (Material-style). */
export function useUndoSnackbar(durationMs = UNDO_SNACKBAR_MS) {
  const [snack, setSnack] = useState<UndoSnack | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const dismiss = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    setSnack(null);
  }, []);

  const showUndo = useCallback(
    (message: string, onUndo: () => void) => {
      dismiss();
      setSnack({ message, onUndo });
      timerRef.current = setTimeout(() => dismiss(), durationMs);
    },
    [dismiss, durationMs],
  );

  const undo = useCallback(() => {
    snack?.onUndo();
    dismiss();
  }, [snack, dismiss]);

  useEffect(() => () => dismiss(), [dismiss]);

  return { snack, showUndo, undo, dismiss };
}
