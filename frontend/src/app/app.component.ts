import { Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';

import { ToastHostComponent } from './shared/ui/toast-host.component';

@Component({
  selector: 'co-root',
  imports: [RouterOutlet, ToastHostComponent],
  template: `
    <a class="skip-link" href="#main-content">Skip to main content</a>
    <router-outlet />
    <co-toast-host />
  `,
  styles: `
    :host {
      display: block;
      min-height: 100dvh;
    }
  `,
})
export class AppComponent {}
