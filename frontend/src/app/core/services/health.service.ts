import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { ApiClient } from '../api/api-client.service';

export interface HealthResponse {
  readonly status: string;
  readonly service: string;
  readonly version: string;
}

@Injectable({ providedIn: 'root' })
export class HealthService {
  private readonly api = inject(ApiClient);

  check(): Observable<HealthResponse> {
    return this.api.get<HealthResponse>('/health');
  }
}
