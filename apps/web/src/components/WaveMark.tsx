import { useId } from "react";

/**
 * The FloatChat mark: three wave lines that drift when `active` (and gently on hover),
 * still otherwise. Pure SVG and CSS, so it costs nothing and respects reduced motion.
 */
export function WaveMark({
  size = 22,
  active = false,
  className = "",
}: {
  size?: number;
  active?: boolean;
  className?: string;
}) {
  const id = useId();
  return (
    <svg
      className={`wave-mark${active ? " wave-mark-active" : ""} ${className}`}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <defs>
        <clipPath id={`${id}-clip`}>
          <rect x="2" y="2" width="20" height="20" rx="4" />
        </clipPath>
      </defs>
      <g clipPath={`url(#${id}-clip)`}>
        {[7, 12, 17].map((y, index) => (
          <path
            key={y}
            className={`wave-line wave-line-${index + 1}`}
            d={`M-14 ${y} q3 -2.4 6 0 t6 0 t6 0 t6 0 t6 0 t6 0 t6 0 t6 0`}
            stroke="currentColor"
            strokeWidth="1.9"
            strokeLinecap="round"
          />
        ))}
      </g>
    </svg>
  );
}
