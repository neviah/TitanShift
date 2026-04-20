import { Composition, registerRoot } from "remotion";
import { HelloVideo } from "./HelloVideo";

export const RemotionRoot = () => (
  <Composition
    id="HelloVideo"
    component={HelloVideo}
    durationInFrames={150}
    fps={30}
    width={1920}
    height={1080}
  />
);

registerRoot(RemotionRoot);
