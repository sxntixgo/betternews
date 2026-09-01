/**
 * Two- and three-up segmented controls. A radiogroup rather than a set of
 * buttons: exactly one option is selected at a time, and that is what
 * `role="radio"` + `aria-checked` says.
 *
 * An option's visible text is `label`; its accessible name is `label` unless
 * `name` overrides it. Score/Date and Dark/Light need no override -- the
 * visible word is exactly what a test or a screen reader should call them.
 * Theme's third option is the one exception: it now reads "Auto" (the
 * three-state preference used to be three unlabelled icons, so there was no
 * visible text to preserve), but `interaction.spec.ts` still finds it by its
 * pre-existing name, "Follow the system". `name` lets the visible word change
 * without renaming the control underneath it.
 */
export function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: readonly { value: T; label: string; name?: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div className="setting-row">
      <span className="setting-label">{label}</span>
      <div className="segmented" role="radiogroup" aria-label={label}>
        {options.map((o) => (
          <button
            key={o.value}
            className="segment"
            role="radio"
            aria-checked={value === o.value}
            aria-label={o.name}
            onClick={() => onChange(o.value)}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}
