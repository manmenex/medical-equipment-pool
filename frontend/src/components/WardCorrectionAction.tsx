import { WardCorrectionDialog } from "@/components/WardCorrectionDialog";
import { canCorrectTransactionWard, useAuth } from "@/hooks/useAuth";
import { useWardCorrection } from "@/hooks/useWardCorrection";
import type { TransactionOut } from "@/types";

interface WardCorrectionActionProps {
  transaction: TransactionOut;
  // The caller decides which query keys to invalidate/refetch for its own
  // screen (e.g. ReturnPage's displayed transaction vs. an equipment
  // history list) -- the mutation, error mapping, and form/validation
  // behavior itself stays centralized in WardCorrectionDialog, never
  // duplicated per screen.
  onCorrected: (updated: TransactionOut, message: string) => void;
  triggerClassName?: string;
  triggerLabel?: string;
}

const DEFAULT_LABEL = "แก้ไขแผนกรับเครื่อง";
const DEFAULT_TRIGGER_CLASSNAME =
  "w-full rounded-lg border border-[var(--border)] py-2.5 text-sm font-medium disabled:opacity-60";

// Roadmap PR9B review round 2 (Finding 1, Finding 3): the single reusable
// "correction action" unit -- current-ward-agnostic trigger button plus its
// ward-list loading/error/retry state and the confirmation dialog -- shared
// between ReturnPage (an OPEN transaction) and EquipmentDetailPage's
// transaction history (OPEN or CLOSED). The backend places no
// lifecycle-status precondition on this endpoint (docs/api/
// transactions.md), so this component never reads or branches on
// transaction.status -- only on canCorrectTransactionWard(user) and the
// ward list's own load state.
export function WardCorrectionAction({
  transaction,
  onCorrected,
  triggerClassName = DEFAULT_TRIGGER_CLASSNAME,
  triggerLabel = DEFAULT_LABEL,
}: WardCorrectionActionProps) {
  const { user } = useAuth();
  const canCorrect = canCorrectTransactionWard(user);
  const { wards, wardsLoading, wardsError, refetchWards, dialogOpen, openDialog, closeDialog, triggerRef } =
    useWardCorrection();

  if (!canCorrect) {
    return null;
  }

  if (wardsLoading) {
    return (
      <button type="button" disabled className={triggerClassName} aria-busy="true">
        กำลังโหลดรายชื่อแผนก...
      </button>
    );
  }

  if (wardsError) {
    return (
      <div className="flex flex-col gap-2">
        <p className="text-sm text-status-repair">ไม่สามารถโหลดรายชื่อแผนกได้</p>
        <button
          type="button"
          onClick={() => refetchWards()}
          className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium"
        >
          ลองใหม่
        </button>
      </div>
    );
  }

  return (
    <>
      <button ref={triggerRef} type="button" onClick={openDialog} className={triggerClassName}>
        {triggerLabel}
      </button>
      {dialogOpen && wards && (
        <WardCorrectionDialog
          transaction={transaction}
          wards={wards}
          triggerRef={triggerRef}
          onClose={closeDialog}
          onUpdated={(updated, message) => {
            closeDialog();
            onCorrected(updated, message);
          }}
        />
      )}
    </>
  );
}
