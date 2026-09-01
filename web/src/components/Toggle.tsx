/**
 * A switch, not a checkbox. `role="switch"` is what makes the state readable
 * to a screen reader and to a test -- the visual is a track and a knob, which
 * on their own say nothing.
 *
 * `label` is the visible text; `name` is the accessible name and defaults to
 * `label`. They diverge for Photos and Compact, whose accessible names
 * ("Show photos", "Compact list") predate this component and are addressed
 * directly by roughly ten passing tests. Passing `label` straight through to
 * `aria-label` would silently rename them to "Photos" / "Compact" and break
 * every one -- WCAG 2.5.3 only requires the visible label be *contained in*
 * the accessible name, not equal to it, so keeping the longer name is both
 * compliant and the smaller diff.
 */
export function Toggle({
  label,
  name = label,
  checked,
  onChange,
}: {
  label: string;
  name?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="setting-row">
      <span className="setting-label">{label}</span>
      <button
        className="toggle"
        role="switch"
        aria-checked={checked}
        aria-label={name}
        onClick={() => onChange(!checked)}
      >
        <span className="toggle-knob" />
      </button>
    </div>
  );
}
