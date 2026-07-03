import { forwardRef } from "react";

interface Props {
  src: string;
  title?: string;
  vertical?: boolean;
}

const WatchPlayer = forwardRef<HTMLVideoElement, Props>(function WatchPlayer(
  { src, title, vertical },
  ref
) {
  return (
    <div className={`v2-player-wrap${vertical ? " v2-player-wrap--vertical" : ""}`}>
      <video ref={ref} src={src} controls playsInline title={title} key={src} />
    </div>
  );
});

export default WatchPlayer;
