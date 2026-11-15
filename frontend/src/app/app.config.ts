import { ApplicationConfig, LOCALE_ID, provideBrowserGlobalErrorListeners } from '@angular/core';
import { registerLocaleData } from '@angular/common';
import { provideHttpClient } from '@angular/common/http';
import localeFrCa from '@angular/common/locales/fr-CA';

// Formats canadiens-français : « -6,38 % », « -636 $ ».
registerLocaleData(localeFrCa);

export const appConfig: ApplicationConfig = {
  providers: [provideBrowserGlobalErrorListeners(), provideHttpClient(), { provide: LOCALE_ID, useValue: 'fr-CA' }],
};
