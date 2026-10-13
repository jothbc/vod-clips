import { forwardRef, useCallback, useRef, type MutableRefObject, type Ref } from "react";
import { useBay } from "../context/BayContext";

function assignRef<T>(ref: Ref<T> | undefined, value: T | null) {
  if (!ref) return;
  if (typeof ref === "function") {
    ref(value);
  } else {
    (ref as MutableRefObject<T | null>).current = value;
  }
}

interface Props {
  src: string;
  title?: string;
  vertical?: boolean;
}

const WatchPlayer = forwardRef<HTMLVideoElement, Props>(function WatchPlayer(
  { src, title, vertical },
  ref
) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const { setWatchVideo } = useBay();

  const setVideoRef = useCallback(
    (node: HTMLVideoElement | null) => {
      videoRef.current = node;
      assignRef(ref, node);
      setWatchVideo(node);
    },
    [ref, setWatchVideo]
  );

  return (
    <div className={`v2-player-wrap${vertical ? " v2-player-wrap--vertical" : ""}`}>
      <video ref={setVideoRef} src={src} controls playsInline title={title} key={src} />
    </div>
  );
});

export default WatchPlayer;
