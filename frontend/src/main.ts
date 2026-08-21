import { bootstrapApplication } from '@angular/platform-browser';

import { AppComponent } from './app/app.component';
import { appConfig } from './app/app.config';

bootstrapApplication(AppComponent, appConfig).catch((error: unknown) => {
  // Bootstrap failures must be visible, not silent.
  console.error('CodeOops failed to start', error);
});
