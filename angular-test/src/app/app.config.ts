import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideRouter, Routes, CanActivateFn, Router } from '@angular/router';
import { inject } from '@angular/core';
import { LoginComponent } from './login.component';
import { DashboardComponent } from './dashboard.component';
import { ChatComponent } from './chat/chat.component';

const authGuard: CanActivateFn = () => {
  const token = sessionStorage.getItem('qw_auth_token');
  if (token) return true;
  inject(Router).navigate(['/login']);
  return false;
};

const routes: Routes = [
  { path: 'login', component: LoginComponent },
  { path: 'chat', component: ChatComponent, canActivate: [authGuard] },
  { path: '', component: DashboardComponent, canActivate: [authGuard] },
  { path: '**', redirectTo: '' },
];

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes),
  ],
};
