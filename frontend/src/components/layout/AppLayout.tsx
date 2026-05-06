import { AppShell, NavLink, Group, Title, Text, ActionIcon, Tooltip } from '@mantine/core';
import {
  IconMessageQuestion,
  IconDatabase,
  IconBook,
  IconChartBar,
  IconVocabulary,
  IconFileText,
  IconHistory,
  IconUsers,
  IconLogout,
  IconListDetails,
} from '@tabler/icons-react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { EmbeddingStatusBanner } from '../common/EmbeddingStatusBanner';
import { clearUserInfo, getUserInfo } from '../../utils/auth';
import { api } from '../../api/client';

const NAV_ITEMS = [
  { label: 'Query', path: '/query', icon: IconMessageQuestion },
  { label: 'Connections', path: '/connections', icon: IconDatabase },
  { label: 'Glossary', path: '/glossary', icon: IconBook },
  { label: 'Metrics', path: '/metrics', icon: IconChartBar },
  { label: 'Dictionary', path: '/dictionary', icon: IconVocabulary },
  { label: 'Knowledge', path: '/knowledge', icon: IconFileText },
  { label: 'Sample Queries', path: '/sample-queries', icon: IconListDetails, adminOnly: true },
  { label: 'History', path: '/history', icon: IconHistory },
  { label: 'Users', path: '/users', icon: IconUsers, adminOnly: true },
];

export function AppLayout() {
  const location = useLocation();
  const navigate = useNavigate();

  // Role is stored in localStorage from the login response body (token is HttpOnly — not accessible to JS)
  const userInfo = getUserInfo();
  const userRole = userInfo?.role ?? 'user';

  // Filter nav items based on role
  const visibleNavItems = NAV_ITEMS.filter(
    (item) => !item.adminOnly || userRole === 'admin'
  );

  async function handleSignOut() {
    try {
      await api.post('/auth/logout');
    } catch {
      // Best-effort — clear local state regardless
    }
    clearUserInfo();
    navigate('/login', { replace: true });
  }

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{ width: 220, breakpoint: 'sm' }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="xs">
            <Title order={3} fw={700}>
              Saras
            </Title>
            <Text size="sm" c="dimmed">
              Ask questions in plain English
            </Text>
          </Group>
          <Tooltip label="Sign out" position="left">
            <ActionIcon variant="subtle" color="gray" onClick={() => void handleSignOut()} aria-label="Sign out">
              <IconLogout size={18} stroke={1.5} />
            </ActionIcon>
          </Tooltip>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="xs">
        {visibleNavItems.map((item) => (
          <NavLink
            key={item.path}
            label={item.label}
            leftSection={<item.icon size={20} stroke={1.5} />}
            active={location.pathname === item.path}
            onClick={() => navigate(item.path)}
            variant="light"
            mb={4}
          />
        ))}
      </AppShell.Navbar>

      <AppShell.Main>
        <EmbeddingStatusBanner />
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}
