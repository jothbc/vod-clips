import { useCallback, useEffect, useRef, useState } from "react";
import {
  cancelV2Job,
  getV2Job,
  subscribeV2JobEvents,
  type JobState,
} from "../api/jobs";

interface Options {
  onCompleted?: (job: JobState) => void;
  onFailed?: (job: JobState) => void;
  onAwaitingReview?: (job: JobState) => void;
}

/** Shared create/subscribe/cancel lifecycle for a single running job. */
export function useJobController(opts: Options = {}) {
  const [job, setJob] = useState<JobState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  const sseUnsubRef = useRef<(() => void) | null>(null);
  const jobIdRef = useRef<string | null>(null);
  const optsRef = useRef(opts);
  optsRef.current = opts;

  const running = starting || job?.status === "running" || job?.status === "queued";

  const closeSse = useCallback(() => {
    sseUnsubRef.current?.();
    sseUnsubRef.current = null;
  }, []);

  useEffect(() => () => closeSse(), [closeSse]);

  const onUpdate = useCallback(
    (expectedJobId: string) => (state: JobState) => {
      if (state.id !== expectedJobId) return;
      setJob(state);
      if (state.status === "completed") {
        setStarting(false);
        optsRef.current.onCompleted?.(state);
      } else if (state.status === "awaiting_review") {
        setStarting(false);
        optsRef.current.onAwaitingReview?.(state);
      } else if (state.status === "failed") {
        setStarting(false);
        optsRef.current.onFailed?.(state);
      }
    },
    []
  );

  const subscribe = useCallback(
    (jobId: string) => {
      closeSse();
      jobIdRef.current = jobId;
      void getV2Job(jobId).then(onUpdate(jobId)).catch(() => {});
      sseUnsubRef.current = subscribeV2JobEvents(jobId, onUpdate(jobId));
    },
    [closeSse, onUpdate]
  );

  const cancel = useCallback(async () => {
    const id = jobIdRef.current;
    if (!id) return;
    try {
      await cancelV2Job(id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const reset = useCallback(() => {
    closeSse();
    jobIdRef.current = null;
    setJob(null);
    setError(null);
    setStarting(false);
  }, [closeSse]);

  return {
    job,
    error,
    starting,
    running,
    jobIdRef,
    setError,
    setStarting,
    subscribe,
    cancel,
    reset,
  };
}
