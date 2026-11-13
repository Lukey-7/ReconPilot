/** NAV sign-off (built in stage 2d). */
import { Placeholder } from "../components/Placeholder";
import { ScreenHeader } from "../components/ScreenHeader";
import { ScreenContext } from "./ScreenContext";

export function SignOffScreen() {
  return (
    <section className="screen">
      <ScreenHeader title="NAV sign-off">
        <ScreenContext />
      </ScreenHeader>
      <Placeholder>
        <p>The sign-off screen is not built yet. The release status above is live.</p>
      </Placeholder>
    </section>
  );
}
