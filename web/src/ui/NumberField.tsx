import { useState, useEffect } from "react";

export function NumberField({
  value,
  onChange,
  min,
  max,
  className,
  disabled,
}: {
  value: number;
  onChange: (n: number) => void;
  min?: number;
  max?: number;
  className?: string;
  disabled?: boolean;
}) {
  const [text, setText] = useState(String(value));

  // Keep local text in sync when the prop changes externally
  useEffect(() => {
    setText(String(value));
  }, [value]);

  const commit = () => {
    const n = parseInt(text, 10);
    if (Number.isNaN(n)) {
      setText(String(value));
      return;
    }
    const clamped = Math.max(min ?? -Infinity, Math.min(max ?? Infinity, n));
    setText(String(clamped));
    onChange(clamped);
  };

  return (
    <input
      type="text"
      inputMode="numeric"
      value={text}
      disabled={disabled}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
      }}
      className={className}
    />
  );
}
