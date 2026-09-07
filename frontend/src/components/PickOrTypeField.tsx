import { useState } from 'react';

interface PickOrTypeFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  /** Existing values to offer in the dropdown (sorted by the caller). */
  options: string[];
  placeholder?: string;
}

/**
 * A dropdown backed by the application's existing option set with a controlled
 * "Add new…" escape hatch that reveals a text input (no unrestricted free-text
 * input by default). Used for Category and Project Life Cycle so values stay
 * consistent with what the AI/matching enrichment and other records use.
 */
export function PickOrTypeField({
  label,
  value,
  onChange,
  options,
  placeholder = 'Select…',
}: PickOrTypeFieldProps) {
  const [adding, setAdding] = useState(false);

  // A stored value outside the known options (or an explicit "Add new…"
  // selection) puts the field into custom-entry mode.
  const isCustom = adding || (value !== '' && !options.includes(value));
  const selectValue = isCustom ? '__custom__' : value;

  function onSelect(next: string) {
    if (next === '__custom__') {
      setAdding(true);
      onChange('');
      return;
    }
    setAdding(false);
    onChange(next);
  }

  return (
    <div className="field">
      <label>{label}</label>
      <select
        value={selectValue}
        onChange={(e) => onSelect(e.target.value)}
      >
        <option value="">{placeholder}</option>
        {options.map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
        <option value="__custom__">Add new…</option>
      </select>
      {isCustom ? (
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Type a new value…"
        />
      ) : null}
    </div>
  );
}
