import { useCallback, useEffect, useState } from "react";
import {
  createJob,
  fetchClips,
  fetchHealth,
  getJob,
  subscribeJobEvents,
  type ClipItem,
  type JobState,
} from "./api/client";
import ClipsGallery from "./components/ClipsGallery";
import CleanupPanel from "./components/CleanupPanel";
import JobForm, { type JobFormValues } from "./components/JobForm";
import ProgressPanel from "./components/ProgressPanel";

const defaultForm: JobFormValues = {
  videoPath: "",
  mode: "auto",
  preset: "twitch_gaming",
  maxClips: 15,
  useNvenc: true,
  cleanup: false,
  resume: false,
};

export default function App() {
  const [form, setForm] = useState<JobFormValues>(defaultForm);
  const [job, setJob] = useState<JobState | null>(null);
  const [clips, setClips] = useState<ClipItem[]>([]);
  const [outputDir, setOutputDir] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<{ ffmpeg: boolean; ollama: boolean } | null>(null);
  const [cleared, setCleared] = useState(false);

  const running = job?.status === "running" || job?.status === "queued";

  useEffect(() => {
    fetchHealth().then(setHealth).catch(() => setHealth(null));
  }, []);

  const loadClips = useCallback(async (jobId: string) => {
    try {
      const data = await fetchClips(jobId);
      setClips(data.clips);
      setOutputDir(data.output_dir);
    } catch {
      /* not ready yet */
    }
  }, []);

  const startJob = async () => {
    setError(null);
    setClips([]);
    setCleared(false);
    try {
      const { job_id } = await createJob({
        video_path: form.videoPath.trim(),
        preset: form.preset,
        mode: form.mode,
        max_clips: form.maxClips,
        use_nvenc: form.useNvenc,
        cleanup: form.cleanup,
        resume: form.resume,
      });

      const initial = await getJob(job_id);
      setJob(initial);

      const unsub = subscribeJobEvents(
        job_id,
        (state) => {
          setJob(state);
          if (state.status === "completed") {
            loadClips(job_id);
          }
        },
        () => {
          getJob(job_id).then(setJob).catch(() => {});
        }
      );

      return () => unsub();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <>
      <h1>Reels</h1>
      <p className="subtitle">Twitch VOD → YouTube + Instagram Reels (100% local)</p>

      {error && <p className="error">{error}</p>}

      <JobForm
        values={form}
        onChange={setForm}
        onSubmit={startJob}
        disabled={!!running}
        health={health}
      />

      <ProgressPanel job={job} />

      {job && (job.status === "completed" || job.status === "failed") && (
        <>
          {job.status === "completed" && !cleared && (
            <ClipsGallery clips={clips} outputDir={outputDir || job.output_dir} />
          )}
          <CleanupPanel
            jobId={job.id}
            disabled={running}
            onCleared={() => {
              setCleared(true);
              setClips([]);
              setForm((f) => ({ ...f, videoPath: "" }));
            }}
          />
        </>
      )}
    </>
  );
}
