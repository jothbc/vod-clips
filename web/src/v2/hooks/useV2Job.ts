import { useCallback } from "react";
import { useJobController } from "../../hooks/useJobController";
import type { JobState } from "../../api/client";

/** Thin wrapper around legacy job controller for v2 async flows. */
export function useV2Job(opts?: {
  onCompleted?: (job: JobState) => void;
  onFailed?: (job: JobState) => void;
  onAwaitingReview?: (job: JobState) => void;
}) {
  const ctrl = useJobController(opts);

  const waitForJob = useCallback(
    (jobId: string) => {
      ctrl.subscribe(jobId);
    },
    [ctrl]
  );

  return { ...ctrl, waitForJob };
}
