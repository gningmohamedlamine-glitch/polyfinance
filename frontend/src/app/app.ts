import { Component } from '@angular/core';
import { Explorer } from './pages/explorer/explorer';

@Component({
  selector: 'app-root',
  imports: [Explorer],
  template: '<app-explorer />',
})
export class App {}
