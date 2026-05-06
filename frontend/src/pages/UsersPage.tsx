import { useState, useEffect } from 'react';
import {
  Stack,
  Title,
  Button,
  Group,
  Table,
  Modal,
  NumberInput,
  TextInput,
  Select,
  ActionIcon,
  Tooltip,
  Badge,
  Switch,
  Loader,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { notifications } from '@mantine/notifications';
import { IconPlus, IconTrash, IconEdit } from '@tabler/icons-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { usersApi } from '../api/usersApi';
import type { User } from '../types/api';

export function UsersPage() {
  const [addOpen, setAddOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);

  const qc = useQueryClient();

  const { data: users, isLoading } = useQuery({
    queryKey: ['users'],
    queryFn: () => usersApi.list(),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => usersApi.delete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['users'] });
      notifications.show({
        title: 'User deleted',
        message: 'User has been removed',
        color: 'green',
      });
    },
  });

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>Users</Title>
        <Button
          leftSection={<IconPlus size={16} />}
          onClick={() => setAddOpen(true)}
        >
          Add User
        </Button>
      </Group>

      {isLoading && (
        <Group justify="center" py="xl">
          <Loader />
        </Group>
      )}

      {users && users.length > 0 && (
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Email</Table.Th>
              <Table.Th>Role</Table.Th>
              <Table.Th>Resource ID</Table.Th>
              <Table.Th>Employee ID</Table.Th>
              <Table.Th>Status</Table.Th>
              <Table.Th w={80}>Actions</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {users.map((user: User) => (
              <Table.Tr key={user.id}>
                <Table.Td>{user.email}</Table.Td>
                <Table.Td>
                  <Badge
                    color={
                      user.role === 'admin'
                        ? 'red'
                        : user.role === 'manager'
                        ? 'blue'
                        : 'gray'
                    }
                    variant="light"
                  >
                    {user.role}
                  </Badge>
                </Table.Td>
                <Table.Td>{user.resource_id ?? '-'}</Table.Td>
                <Table.Td>{user.employee_id ?? '-'}</Table.Td>
                <Table.Td>
                  <Badge color={user.is_active ? 'green' : 'gray'} variant="light">
                    {user.is_active ? 'Active' : 'Inactive'}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  <Group gap={4}>
                    <Tooltip label="Edit">
                      <ActionIcon
                        variant="subtle"
                        size="sm"
                        onClick={() => setEditingUser(user)}
                      >
                        <IconEdit size={14} />
                      </ActionIcon>
                    </Tooltip>
                    <Tooltip label="Delete">
                      <ActionIcon
                        variant="subtle"
                        color="red"
                        size="sm"
                        onClick={() => {
                          if (confirm(`Delete "${user.email}"?`)) {
                            deleteMutation.mutate(user.id);
                          }
                        }}
                      >
                        <IconTrash size={14} />
                      </ActionIcon>
                    </Tooltip>
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}

      <UserFormModal
        opened={addOpen || !!editingUser}
        onClose={() => {
          setAddOpen(false);
          setEditingUser(null);
        }}
        user={editingUser}
      />
    </Stack>
  );
}

function UserFormModal({
  opened,
  onClose,
  user,
}: {
  opened: boolean;
  onClose: () => void;
  user: User | null;
}) {
  const qc = useQueryClient();
  const isEdit = !!user;

  const form = useForm({
    initialValues: {
      email: '',
      password: '',
      role: '' as 'admin' | 'manager' | 'user' | '',
      resource_id: null as number | null,
      employee_id: '',
      is_active: true,
    },
  });

  useEffect(() => {
    if (user) {
      form.setValues({
        email: user.email,
        password: '',
        role: user.role,
        resource_id: user.resource_id,
        employee_id: user.employee_id ?? '',
        is_active: user.is_active,
      });
    } else {
      form.reset();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  const mutation = useMutation({
    mutationFn: (values: Record<string, unknown>) => {
      if (isEdit) {
        const updateData: Record<string, unknown> = {
          email: values.email,
          role: values.role,
          resource_id: values.resource_id != null ? Number(values.resource_id) : null,
          employee_id: values.employee_id || null,
          is_active: values.is_active,
        };
        if (values.password) {
          updateData.password = values.password;
        }
        return usersApi.update(user!.id, updateData);
      }
      return usersApi.create({
        email: values.email as string,
        password: values.password as string,
        role: values.role as 'admin' | 'manager' | 'user',
        resource_id: values.resource_id as number | undefined,
        employee_id: values.employee_id as string | undefined,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['users'] });
      notifications.show({
        title: isEdit ? 'User updated' : 'User created',
        message: isEdit ? 'User has been updated' : 'User has been created',
        color: 'green',
      });
      form.reset();
      onClose();
    },
  });

  const handleClose = () => {
    form.reset();
    onClose();
  };

  return (
    <Modal
      opened={opened}
      onClose={handleClose}
      title={isEdit ? 'Edit User' : 'Add User'}
      size="md"
    >
      <form onSubmit={form.onSubmit((v) => mutation.mutate(v))}>
        <Stack gap="sm">
          <TextInput
            label="Email"
            required
            {...form.getInputProps('email')}
          />
          <TextInput
            label="Password"
            required={!isEdit}
            type="password"
            placeholder={isEdit ? 'Leave blank to keep current' : undefined}
            {...form.getInputProps('password')}
          />
          <Select
            label="Role"
            data={[
              { value: 'admin', label: 'Admin' },
              { value: 'manager', label: 'Manager' },
              { value: 'user', label: 'User' },
            ]}
            required
            {...form.getInputProps('role')}
          />
          <NumberInput
            label="Resource ID"
            {...form.getInputProps('resource_id')}
          />
          <TextInput
            label="Employee ID"
            {...form.getInputProps('employee_id')}
          />
          {isEdit && (
            <Switch
              label="Active"
              {...form.getInputProps('is_active', { type: 'checkbox' })}
            />
          )}
          <Group justify="flex-end">
            <Button variant="subtle" onClick={handleClose}>
              Cancel
            </Button>
            <Button type="submit" loading={mutation.isPending}>
              {isEdit ? 'Update' : 'Create'}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}