import { Injectable, signal } from '@angular/core';

export type ToastTone = 'info' | 'success' | 'error';

export interface Toast {
  readonly id: number;
  readonly tone: ToastTone;
  readonly title: string;
  readonly message?: string;
}

const DISMISS_AFTER_MS: Record<ToastTone, number> = {
  info: 5000,
  success: 5000,
  error: 9000,
};

/**
 * Non-blocking notifications.
 *
 * The application never uses `window.alert`/`confirm`; every message the user
 * needs goes through here and is announced in an aria-live region.
 */
@Injectable({ providedIn: 'root' })
export class ToastService {
  private nextId = 1;
  private readonly items = signal<readonly Toast[]>([]);

  readonly toasts = this.items.asReadonly();

  show(tone: ToastTone, title: string, message?: string): number {
    const id = this.nextId++;
    this.items.set([...this.items(), { id, tone, title, message }]);
    if (typeof window !== 'undefined') {
      window.setTimeout(() => this.dismiss(id), DISMISS_AFTER_MS[tone]);
    }
    return id;
  }

  info(title: string, message?: string): number {
    return this.show('info', title, message);
  }

  success(title: string, message?: string): number {
    return this.show('success', title, message);
  }

  error(title: string, message?: string): number {
    return this.show('error', title, message);
  }

  dismiss(id: number): void {
    this.items.set(this.items().filter((toast) => toast.id !== id));
  }

  clear(): void {
    this.items.set([]);
  }
}
