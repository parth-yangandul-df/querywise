import { useState } from 'react';
import { AppShell, NavLink, Group, Title, Text, ActionIcon, Tooltip, Burger, useMantineColorScheme } from '@mantine/core';
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
  IconMoon,
  IconSun,
} from '@tabler/icons-react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { EmbeddingStatusBanner } from '../common/EmbeddingStatusBanner';
import { clearUserInfo, getUserInfo } from '../../utils/auth';
import { api } from '../../api/client';

function ColorSchemeToggle() {
  const { colorScheme, toggleColorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';

  return (
    <Tooltip label={isDark ? 'Switch to light mode' : 'Switch to dark mode'} position="left">
      <ActionIcon
        variant="subtle"
        color="gray"
        onClick={() => toggleColorScheme()}
        aria-label="Toggle color scheme"
      >
        {isDark ? <IconSun size={18} stroke={1.5} /> : <IconMoon size={18} stroke={1.5} />}
      </ActionIcon>
    </Tooltip>
  );
}

const NAV_ITEMS = [
  { label: 'Query', path: '/query', icon: IconMessageQuestion },
  { label: 'History', path: '/history', icon: IconHistory },
  { label: 'Connections', path: '/connections', icon: IconDatabase, adminOnly: true },
  { label: 'Glossary', path: '/glossary', icon: IconBook, adminOnly: true },
  { label: 'Metrics', path: '/metrics', icon: IconChartBar, adminOnly: true },
  { label: 'Dictionary', path: '/dictionary', icon: IconVocabulary, adminOnly: true },
  { label: 'Knowledge', path: '/knowledge', icon: IconFileText, adminOnly: true },
  { label: 'Sample Queries', path: '/sample-queries', icon: IconListDetails, adminOnly: true },
  { label: 'Users', path: '/users', icon: IconUsers, adminOnly: true },
];

export function AppLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const [navbarOpened, setNavbarOpened] = useState(true);

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
      navbar={{ width: 220, breakpoint: 'sm', collapsed: { desktop: !navbarOpened, mobile: !navbarOpened } }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="xs">
            <Burger
              opened={navbarOpened}
              onClick={() => setNavbarOpened((o) => !o)}
              size="sm"
              aria-label="Toggle sidebar"
            />
            <Title order={3} fw={700}>
              Saras
            </Title>
            <Text size="sm" c="dimmed">
              Ask questions in plain English
            </Text>
          </Group>
          <Group gap="xs">
            <ColorSchemeToggle />
            <Tooltip label="Sign out" position="left">
              <ActionIcon variant="subtle" color="gray" onClick={() => void handleSignOut()} aria-label="Sign out">
                <IconLogout size={18} stroke={1.5} />
              </ActionIcon>
            </Tooltip>
          </Group>
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
