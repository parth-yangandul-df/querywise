import { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  Box,
  Button,
  Card,
  Group,
  PasswordInput,
  Stack,
  Text,
  TextInput,
  Title,
  Alert,
  Badge,
  Divider,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { IconAlertCircle, IconDatabase } from '@tabler/icons-react';

import { api } from '../api/client';
import { setUserInfo } from '../utils/auth';
import type { UserInfo } from '../utils/auth';

const DEV_ACCOUNTS = [
  { label: 'Admin', email: 'admin@querywise.dev', password: 'admin123', color: 'red' },
  { label: 'Manager', email: 'manager@querywise.dev', password: 'manager123', color: 'blue' },
  { label: 'User', email: 'user@querywise.dev', password: 'user123', color: 'green' },
] as const;

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string })?.from ?? '/';

  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const form = useForm({
    initialValues: { email: '', password: '' },
    validate: {
      email: (v) => (/\S+@\S+\.\S+/.test(v) ? null : 'Enter a valid email'),
      password: (v) => (v.length > 0 ? null : 'Password is required'),
    },
  });

  async function handleSubmit(values: { email: string; password: string }) {
    setLoading(true);
    setError(null);
    try {
      // Backend sets access_token HttpOnly cookie + csrf_token cookie.
      // Response body carries user info only (no token).
      const res = await api.post<UserInfo>('/auth/login', values);
      setUserInfo(res.data);
      navigate(from, { replace: true });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Login failed';
      setError(msg === 'Invalid token' || msg.toLowerCase().includes('credentials')
        ? 'Invalid email or password'
        : msg);
    } finally {
      setLoading(false);
    }
  }

  function quickFill(email: string, password: string) {
    form.setValues({ email, password });
    setError(null);
  }

  return (
    <Box
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'var(--mantine-color-gray-0)',
      }}
    >
      <Card shadow="sm" padding="xl" radius="md" w={420} withBorder>
        <Stack gap="lg">
          {/* Header */}
          <Stack gap={4} align="center">
            <Group gap="xs">
              <IconDatabase size={28} color="var(--mantine-color-blue-6)" />
              <Title order={2} fw={700}>
                QueryWise
              </Title>
            </Group>
            <Text c="dimmed" size="sm">
              Sign in to continue
            </Text>
          </Stack>

          {/* Error banner */}
          {error && (
            <Alert icon={<IconAlertCircle size={16} />} color="red" variant="light">
              {error}
            </Alert>
          )}

          {/* Login form */}
          <form onSubmit={form.onSubmit(handleSubmit)}>
            <Stack gap="sm">
              <TextInput
                label="Email"
                placeholder="you@example.com"
                autoComplete="email"
                {...form.getInputProps('email')}
              />
              <PasswordInput
                label="Password"
                placeholder="••••••••"
                autoComplete="current-password"
                {...form.getInputProps('password')}
              />
              <Button type="submit" fullWidth loading={loading} mt="xs">
                Sign in
              </Button>
            </Stack>
          </form>

          {/* Dev quick-fill (development only) */}
          {import.meta.env.DEV && (
            <>
              <Divider label="Dev accounts" labelPosition="center" />
              <Group gap="xs" justify="center">
                {DEV_ACCOUNTS.map((a) => (
                  <Badge
                    key={a.label}
                    color={a.color}
                    variant="light"
                    style={{ cursor: 'pointer' }}
                    onClick={() => quickFill(a.email, a.password)}
                  >
                    {a.label}
                  </Badge>
                ))}
              </Group>
              <Text size="xs" c="dimmed" ta="center">
                Click a badge to fill credentials, then sign in
              </Text>
            </>
          )}
        </Stack>
      </Card>
    </Box>
  );
}
