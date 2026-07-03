export type TrimSegment = {
  id: string;
  start: number;
  end: number;
};

export const MIN_TRIM_SEGMENT_SEC = 0.25;

export function initialSegments(duration: number): TrimSegment[] {
  return [{ id: newSegmentId(), start: 0, end: Math.max(0, duration) }];
}

export function newSegmentId(): string {
  return `seg_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
}

export function splitAt(segments: TrimSegment[], time: number, duration: number): TrimSegment[] {
  const t = Math.max(0, Math.min(duration, time));
  const idx = segments.findIndex(
    (s) => t > s.start + MIN_TRIM_SEGMENT_SEC && t < s.end - MIN_TRIM_SEGMENT_SEC
  );
  if (idx < 0) return segments;

  const seg = segments[idx];
  const left: TrimSegment = { id: newSegmentId(), start: seg.start, end: t };
  const right: TrimSegment = { id: newSegmentId(), start: t, end: seg.end };
  return [...segments.slice(0, idx), left, right, ...segments.slice(idx + 1)];
}

export function deleteSegment(segments: TrimSegment[], id: string): TrimSegment[] {
  if (segments.length <= 1) return segments;
  const next = segments.filter((s) => s.id !== id);
  return next.length ? next : segments;
}

export function duplicateSegment(segments: TrimSegment[], id: string): TrimSegment[] {
  const idx = segments.findIndex((s) => s.id === id);
  if (idx < 0) return segments;
  const seg = segments[idx];
  const copy: TrimSegment = { id: newSegmentId(), start: seg.start, end: seg.end };
  return [...segments.slice(0, idx + 1), copy, ...segments.slice(idx + 1)];
}

export function reorderSegments(
  segments: TrimSegment[],
  dragId: string,
  targetId: string
): TrimSegment[] {
  if (dragId === targetId) return segments;
  const from = segments.findIndex((s) => s.id === dragId);
  const to = segments.findIndex((s) => s.id === targetId);
  if (from < 0 || to < 0) return segments;
  const next = [...segments];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
}

export function totalKeptDuration(segments: TrimSegment[]): number {
  return segments.reduce((acc, s) => acc + Math.max(0, s.end - s.start), 0);
}

/** Export spans in playlist order (duplicates and reorder preserved). */
export function toKeepSpans(segments: TrimSegment[]): [number, number][] {
  return segments.map((s) => [s.start, s.end] as [number, number]);
}

function mergedTimeRanges(segments: TrimSegment[]): [number, number][] {
  const sorted = [...segments]
    .map((s) => [s.start, s.end] as [number, number])
    .sort((a, b) => a[0] - b[0]);
  const merged: [number, number][] = [];
  for (const [start, end] of sorted) {
    const last = merged[merged.length - 1];
    if (last && start <= last[1] + MIN_TRIM_SEGMENT_SEC) {
      last[1] = Math.max(last[1], end);
    } else {
      merged.push([start, end]);
    }
  }
  return merged;
}

export function gapsBetweenSegments(segments: TrimSegment[], duration: number): [number, number][] {
  const kept = mergedTimeRanges(segments);
  const gaps: [number, number][] = [];
  let cursor = 0;
  for (const [start, end] of kept) {
    if (start > cursor + MIN_TRIM_SEGMENT_SEC) {
      gaps.push([cursor, start]);
    }
    cursor = Math.max(cursor, end);
  }
  if (cursor < duration - MIN_TRIM_SEGMENT_SEC) {
    gaps.push([cursor, duration]);
  }
  return gaps;
}

export function overlapCountAt(segments: TrimSegment[], seg: TrimSegment): number {
  return segments.filter(
    (s) => s.start < seg.end - 0.01 && s.end > seg.start + 0.01
  ).length;
}
