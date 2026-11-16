/** The keyboard shortcuts dialog (?): lists every shortcut registered right now, by group. */
import * as Dialog from "@radix-ui/react-dialog";

import { Icon } from "../components/Icon";
import { keyNames } from "../components/Kbd";
import { useReturnFocus } from "../components/returnFocus";
import { useGroupedShortcuts } from "../keyboard/KeyboardProvider";

/** "g o" as G then O; "mod+k" as Ctrl and K pressed together. */
function Keys({ keys }: { keys: string }) {
  const parts = keys.split(" ");
  return (
    <span className="keys">
      {parts.map((k, i) => (
        <span key={i}>
          {i > 0 && <span className="then">then</span>}
          {keyNames(k).map((name, j) => (
            <kbd key={j}>{name}</kbd>
          ))}
        </span>
      ))}
    </span>
  );
}

export function HelpDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const groups = useGroupedShortcuts();
  const returnFocus = useReturnFocus(open);
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="scrim" />
        <Dialog.Content className="dialog help-dialog" onCloseAutoFocus={returnFocus}>
          <div className="dialog-head">
            <Dialog.Title>Keyboard shortcuts</Dialog.Title>
            <Dialog.Close className="btn ghost icon-btn" aria-label="Close">
              <Icon name="cross" />
            </Dialog.Close>
          </div>
          <Dialog.Description className="muted">
            Shortcuts work anywhere except while you are typing in a field; Esc leaves the field. Ctrl+K works
            everywhere.
          </Dialog.Description>
          {groups.map(([group, items]) => (
            <section key={group} className="help-group" aria-label={group}>
              <h3>{group}</h3>
              <dl>
                {items.map((s) => (
                  <div key={s.keys} className="help-row">
                    <dt>
                      <Keys keys={s.keys} />
                    </dt>
                    <dd>{s.description}</dd>
                  </div>
                ))}
              </dl>
            </section>
          ))}
          <section className="help-group" aria-label="Fields and dialogs">
            <h3>Fields and dialogs</h3>
            <dl>
              <div className="help-row">
                <dt>
                  <Keys keys="Escape" />
                </dt>
                <dd>Leave the field you are typing in, or close the open dialog, menu or popover</dd>
              </div>
            </dl>
          </section>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
