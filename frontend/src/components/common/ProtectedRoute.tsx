import { Center, Loader } from '@mantine/core';
import { Navigate, Outlet, useLocation } from 'react-router-dom';

import { useSession } from '../../hooks/useSession';
import { isAuthenticated } from '../../utils/auth';

export function ProtectedRoute() {
  const location = useLocation();
  const { isLoading } = useSession();

  if (!isAuthenticated()) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }

  if (isLoading) {
    return (
      <Center h="100vh">
        <Loader />
      </Center>
    );
  }

  return <Outlet />;
}
