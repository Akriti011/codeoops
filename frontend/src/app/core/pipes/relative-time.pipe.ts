import { Pipe, PipeTransform } from '@angular/core';

const UNITS: readonly { readonly limit: number; readonly divisor: number; readonly unit: Intl.RelativeTimeFormatUnit }[] = [
  { limit: 60, divisor: 1, unit: 'second' },
  { limit: 3600, divisor: 60, unit: 'minute' },
  { limit: 86400, divisor: 3600, unit: 'hour' },
  { limit: 604800, divisor: 86400, unit: 'day' },
  { limit: 2629800, divisor: 604800, unit: 'week' },
  { limit: 31557600, divisor: 2629800, unit: 'month' },
];

const formatter = typeof Intl !== 'undefined' ? new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' }) : null;

/**
 * Formats an ISO timestamp as a short relative string ("2 min ago").
 * Pure: recomputes only when the input changes, no timer involved.
 */
@Pipe({ name: 'relativeTime', standalone: true, pure: true })
export class RelativeTimePipe implements PipeTransform {
  transform(value: string | null | undefined): string {
    if (!value) {
      return 'Not available';
    }

    const then = new Date(value).getTime();
    if (Number.isNaN(then)) {
      return 'Not available';
    }

    const diffSeconds = (Date.now() - then) / 1000;

    if (!formatter) {
      return new Date(value).toLocaleString();
    }

    if (diffSeconds < 45) {
      return 'Just now';
    }

    for (const { limit, divisor, unit } of UNITS) {
      if (diffSeconds < limit) {
        return formatter.format(-Math.round(diffSeconds / divisor), unit);
      }
    }

    return formatter.format(-Math.round(diffSeconds / 31557600), 'year');
  }
}
