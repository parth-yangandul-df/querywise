import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { clearUserInfo, isAuthenticated } from '../utils/auth';
import type { UserInfo } from '../utils/auth';

export function useSession() {
  return useQuery({
    queryKey: ['session'],
    queryFn: async () => {
      if (!isAuthenticated()) return null;
      try {
        const res = await api.get<UserInfo>('/auth/me');
        return res.data;
      } catch {
        clearUserInfo();
        return null;
      }
    },
    retry: false,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
  });
}
