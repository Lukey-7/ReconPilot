/** The keyboard shortcuts dialog (?): lists every shortcut registered right now, by group. */
import * as Dialog from "@radix-ui/react-dialog";

import { Icon } from "../components/Icon";
import { useGroupedShortcuts } from "../keyboard/KeyboardProvider";

function Keys({ keys }: { keys: string }) {
  const parts = keys.split(" ");
  return (
    <span className="keys">
      {parts.map((k, i) => (
        <span key={i}>
          {i > 0 && <span className="then">then</span>}
          <kbd>{k === "Escape" ? "Esc" : k.replace("mod+", "Ctrl+")}</kbd>
        </span>
      ))}
    </span>
  );
}

export function HelpDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const groups = useGroupedShortcuts();
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="scrim" />
        <Dialog.Content className="dialog help-dialog">
          <div className="dialog-head">
            <Dialog.Title>Keyboard shortcuts</Dialog.Title>
            <Dialog.Close className="btn ghost icon-btn" aria-label="Close">
              <Icon name="cross" />
            </Dialog.Close>
          </div>
          <Dialog.Description className="muted">
            Shortcuts work anywhere except while you are typing in a field.
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
          <section className="help-group" aria-label="Dialogs">
            <h3>Dialogs and menus</h3>
            <dl>
              <div className="help-row">
                <dt>
                  <Keys keys="Escape" />
                </dt>
                <dd>Close the open dialog, menu or popover</dd>
              </div>
            </dl>
          </section>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
