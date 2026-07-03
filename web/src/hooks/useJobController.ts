import { useCallback, useEffect, useRef, useState } from "react";
import {
  cancelJob,
  createJob,
  getJob,
  subscribeJobEvents,
  type CreateJobBody,
  type JobState,
} from "../api/client";

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
      void getJob(jobId).then(onUpdate(jobId)).catch(() => {});
      sseUnsubRef.current = subscribeJobEvents(jobId, onUpdate(jobId));
    },
    [closeSse, onUpdate]
  );

  const start = useCallback(
    async (body: CreateJobBody): Promise<string | null> => {
      closeSse();
      setStarting(true);
      setJob(null);
      setError(null);
      const previousJobId = jobIdRef.current;
      try {
        const { job_id } = await createJob({ ...body, previous_job_id: previousJobId });
        jobIdRef.current = job_id;
        const initial = await getJob(job_id);
        setJob(initial);
        subscribe(job_id);
        return job_id;
      } catch (e) {
        setStarting(false);
        setError(e instanceof Error ? e.message : String(e));
        return null;
      }
    },
    [closeSse, subscribe]
  );

  const cancel = useCallback(async () => {
    const id = jobIdRef.current;
    if (!id) return;
    try {
      await cancelJob(id);
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
    start,
    subscribe,
    cancel,
    reset,
  };
}
