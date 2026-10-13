import { useCallback, useRef, useState, type ReactNode } from "react";
import ConfirmModal from "../components/ConfirmModal";

export interface ConfirmOptions {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
}

interface PendingConfirm extends ConfirmOptions {
  resolve: (ok: boolean) => void;
}

/**
 * Promise-based confirm dialog that replaces window.confirm with an in-app modal.
 * Render `dialog` alongside the component tree (usually near the return root).
 */
export function useConfirmDialog(): {
  confirm: (options: ConfirmOptions) => Promise<boolean>;
  dialog: ReactNode;
} {
  const [pending, setPending] = useState<PendingConfirm | null>(null);
  const pendingRef = useRef<PendingConfirm | null>(null);

  const settle = useCallback((ok: boolean) => {
    const current = pendingRef.current;
    pendingRef.current = null;
    setPending(null);
    current?.resolve(ok);
  }, []);

  const confirm = useCallback((options: ConfirmOptions) => {
    return new Promise<boolean>((resolve) => {
      // Auto-reject any previous pending confirm (should be rare)
      if (pendingRef.current) {
        pendingRef.current.resolve(false);
      }
      const next: PendingConfirm = { ...options, resolve };
      pendingRef.current = next;
      setPending(next);
    });
  }, []);

  const dialog = pending ? (
    <ConfirmModal
      title={pending.title}
      message={pending.message}
      confirmLabel={pending.confirmLabel}
      cancelLabel={pending.cancelLabel}
      danger={pending.danger}
      onConfirm={() => settle(true)}
      onCancel={() => settle(false)}
    />
  ) : null;

  return { confirm, dialog };
}
