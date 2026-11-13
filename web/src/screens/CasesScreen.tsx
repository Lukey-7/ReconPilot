/** The case workbench (built in stage 2c). */
import { Placeholder } from "../components/Placeholder";
import { ScreenHeader } from "../components/ScreenHeader";
import { ScreenContext } from "./ScreenContext";

export function CasesScreen() {
  return (
    <section className="screen">
      <ScreenHeader title="Cases">
        <ScreenContext />
      </ScreenHeader>
      <Placeholder>
        <p>The case workbench is not built yet.</p>
      </Placeholder>
    </section>
  );
}
