import { Pipe, PipeTransform } from '@angular/core';

const UNITS: readonly string[] = ['B', 'KB', 'MB', 'GB', 'TB'];

/**
 * Formats a byte count as a short human-readable size ("2.3 MB").
 * Pure: recomputes only when the input changes.
 */
@Pipe({ name: 'fileSize', standalone: true, pure: true })
export class FileSizePipe implements PipeTransform {
  transform(value: number | null | undefined): string {
    if (value === null || value === undefined || Number.isNaN(value) || value < 0) {
      return 'Not available';
    }
    if (value === 0) {
      return '0 B';
    }

    const exponent = Math.min(Math.floor(Math.log(value) / Math.log(1024)), UNITS.length - 1);
    const scaled = value / 1024 ** exponent;
    const precision = exponent === 0 ? 0 : 1;
    return `${scaled.toFixed(precision)} ${UNITS[exponent]}`;
  }
}
