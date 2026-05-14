import { Navigate, Outlet } from 'react-router-dom';
import { notifications } from '@mantine/notifications';

import { getUserInfo } from '../../utils/auth';

interface RequiredRoleProps {
  roles: string[];
}

export function RequiredRole({ roles }: RequiredRoleProps) {
  const userInfo = getUserInfo();
  const userRole = userInfo?.role ?? '';

  if (!roles.includes(userRole)) {
    setTimeout(() => {
      notifications.show({
        title: 'Access denied',
        message: "You don't have permission to access this page.",
        color: 'red',
        autoClose: 4000,
      });
    }, 0);
    return <Navigate to="/query" replace />;
  }

  return <Outlet />;
}
