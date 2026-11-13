/** The morning overview (built in stage 2b from GET .../overview). */
import { Placeholder } from "../components/Placeholder";
import { ScreenHeader } from "../components/ScreenHeader";
import { ScreenContext } from "./ScreenContext";

export function OverviewScreen() {
  return (
    <section className="screen">
      <ScreenHeader title="Morning overview">
        <ScreenContext />
      </ScreenHeader>
      <Placeholder>
        <p>The morning overview is not built yet. The NAV and release status above are live.</p>
      </Placeholder>
    </section>
  );
}
