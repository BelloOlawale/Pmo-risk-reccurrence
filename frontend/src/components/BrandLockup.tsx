import { BRAND_LINE_1, BRAND_LINE_2 } from '../branding';

/**
 * The product wordmark, rendered as two cohesive lines:
 *
 *   PMO RISK
 *   INTELLIGENCE
 *
 * Sized by the consuming layout via a modifier class (see index.css). Wragby
 * Blue carries the structure; the second line is the prominent, bold element.
 */
export function BrandLockup({ className = '' }: { className?: string }) {
  return (
    <span className={`brand-lockup ${className}`.trim()}>
      <span className="brand-lockup-line1">{BRAND_LINE_1}</span>
      <span className="brand-lockup-line2">{BRAND_LINE_2}</span>
    </span>
  );
}
